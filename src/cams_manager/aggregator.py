"""Segment aggregator for merging short segments into longer files"""

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


logger = logging.getLogger(__name__)


class SegmentAggregator:
    """Merges short segments into longer files"""

    def __init__(
        self,
        name: str,
        segments_dir: Path,
        merged_dir: Path,
        merge_interval: int,
        merge_delay: int,
    ):
        self.name = name
        self.segments_dir = Path(segments_dir)
        self.merged_dir = Path(merged_dir)
        self.merge_interval = merge_interval
        self.merge_delay = merge_delay

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Create merged directory if it doesn't exist
        self.merged_dir.mkdir(parents=True, exist_ok=True)

    def _parse_filename_time(self, filename: str) -> datetime | None:
        """Parse datetime from filename format: YYYYMMDD_HHMMSS.mp4"""
        try:
            # Remove extension
            name_without_ext = filename.rsplit(".", 1)[0]
            return datetime.strptime(name_without_ext, "%Y%m%d_%H%M%S")
        except ValueError:
            return None

    def _get_time_key(self, dt: datetime) -> str:
        """Get time key for grouping (YYYYMMDD_HHMM)"""
        return dt.strftime("%Y%m%d_%H%M")

    def _group_segments_by_minute(self, segments: list[Path]) -> dict[str, list[Path]]:
        """Group segments by minute"""
        groups = defaultdict(list)

        for segment in segments:
            filename_time = self._parse_filename_time(segment.name)
            if filename_time is None:
                logger.warning(
                    f"[{self.name}] Cannot parse time from filename: {segment.name}"
                )
                continue

            time_key = self._get_time_key(filename_time)
            groups[time_key].append(segment)

        # Sort segments within each group
        for time_key in groups:
            groups[time_key].sort(key=lambda p: p.name)

        return groups

    def _merge_segments(
        self,
        segments: list[Path],
        output_path: Path,
    ) -> bool:
        """Merge segments using FFmpeg concat demuxer"""
        if not segments:
            return False

        # Filter out incomplete/corrupted segments
        valid_segments = []
        for segment in segments:
            if not segment.exists():
                logger.warning(f"[{self.name}] Segment file does not exist: {segment}")
                continue

            try:
                file_size = segment.stat().st_size
                # Check if file is too small (likely incomplete)
                if file_size < 1024:  # Less than 1KB is likely incomplete
                    logger.warning(
                        f"[{self.name}] Skipping small/incomplete segment: {segment.name} "
                        f"(size: {file_size} bytes)"
                    )
                    continue

                # Check if file has valid video stream and duration using ffprobe
                probe_cmd = [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=codec_type,nb_read_packets",
                    "-of",
                    "json",
                    str(segment),
                ]
                probe_result = subprocess.run(
                    probe_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )

                if probe_result.returncode != 0:
                    logger.warning(
                        f"[{self.name}] Skipping corrupted/incomplete segment: {segment.name} "
                        f"(ffprobe failed: {probe_result.stderr.decode('utf-8', errors='ignore')[:100]})"
                    )
                    continue

                # Parse JSON output to validate file integrity
                try:
                    probe_data = json.loads(probe_result.stdout.decode("utf-8"))

                    # Check if there are any streams
                    streams = probe_data.get("streams", [])
                    if not streams:
                        logger.warning(
                            f"[{self.name}] Skipping segment without streams: {segment.name}"
                        )
                        continue

                    # Check if there's at least one video stream
                    has_video = any(s.get("codec_type") == "video" for s in streams)
                    if not has_video:
                        logger.warning(
                            f"[{self.name}] Skipping segment without video stream: {segment.name}"
                        )
                        continue

                    # Check if format has valid duration
                    format_info = probe_data.get("format", {})
                    duration = format_info.get("duration")
                    if duration is None or duration == "N/A":
                        logger.warning(
                            f"[{self.name}] Skipping segment with invalid duration: {segment.name} "
                            f"(duration: {duration})"
                        )
                        continue

                    # Check if duration is a valid number and not zero
                    try:
                        duration_float = float(duration)
                        if duration_float <= 0:
                            logger.warning(
                                f"[{self.name}] Skipping segment with zero/negative duration: {segment.name} "
                                f"(duration: {duration_float}s)"
                            )
                            continue
                    except (ValueError, TypeError):
                        logger.warning(
                            f"[{self.name}] Skipping segment with unparseable duration: {segment.name} "
                            f"(duration: {duration})"
                        )
                        continue

                except json.JSONDecodeError as e:
                    logger.warning(
                        f"[{self.name}] Skipping segment with invalid ffprobe output: {segment.name} "
                        f"(JSON error: {e})"
                    )
                    continue

                valid_segments.append(segment)
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"[{self.name}] Timeout checking segment: {segment.name}, skipping"
                )
                continue
            except Exception as e:
                logger.warning(
                    f"[{self.name}] Error checking segment {segment.name}: {e}, skipping"
                )
                continue

        if not valid_segments:
            logger.warning(
                f"[{self.name}] No valid segments to merge (all {len(segments)} segments "
                f"were incomplete or corrupted)"
            )
            return False

        if len(valid_segments) < len(segments):
            logger.warning(
                f"[{self.name}] Filtered out {len(segments) - len(valid_segments)} "
                f"incomplete/corrupted segments, merging {len(valid_segments)} valid ones"
            )

        # Create temporary file list with only valid segments
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            filelist_path = Path(f.name)
            for segment in valid_segments:
                # Use absolute path and escape single quotes
                abs_path = segment.resolve()
                f.write(f"file '{abs_path}'\n")
            f.flush()  # Ensure data is written to buffer
            os.fsync(f.fileno())  # Force write to disk

        if logger.level == logging.DEBUG:
            try:
                with open(filelist_path, "r", encoding="utf-8") as check_f:
                    filelist_content = check_f.read()
                    logger.debug(
                        f"[{self.name}] File list content ({len(filelist_content)} bytes):\n{filelist_content[:200]}"
                    )
            except Exception as e:
                logger.warning(f"[{self.name}] Could not verify file list: {e}")

        # Small delay to ensure file system sync
        time.sleep(0.2)

        try:
            # Use temporary output file first (atomic write)
            # Use .mp4.tmp instead of .tmp so FFmpeg can infer the format
            temp_output = output_path.with_suffix(".mp4.tmp")

            # Build FFmpeg command with protocol whitelist
            cmd = [
                "ffmpeg",
                "-protocol_whitelist",
                "file,concat",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(filelist_path),
                "-c",
                "copy",  # Copy codec, no re-encoding
                "-f",
                "mp4",  # Explicitly specify output format
                "-y",  # Overwrite output file
                str(temp_output),
            ]

            logger.debug(
                f"[{self.name}] Merging {len(valid_segments)} segments into {output_path.name}"
            )
            logger.debug(f"[{self.name}] FFmpeg command: {' '.join(cmd)}")

            # Run FFmpeg
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,  # 5 minutes timeout
            )

            if result.returncode != 0:
                logger.error(
                    f"[{self.name}] FFmpeg merge failed (return code: {result.returncode})"
                )
                logger.error(f"[{self.name}] FFmpeg stderr: {result.stderr}")
                # Log file list content for debugging
                try:
                    with open(filelist_path, "r", encoding="utf-8") as debug_f:
                        logger.error(
                            f"[{self.name}] File list content:\n{debug_f.read()}"
                        )
                except Exception:
                    pass
                # Clean up temp file
                if temp_output.exists():
                    temp_output.unlink()
                return False

            # Atomic rename
            temp_output.rename(output_path)
            logger.info(
                f"[{self.name}] Successfully merged {len(valid_segments)} segments "
                f"into {output_path.name}"
            )

            # Delete merged segments (only valid ones that were successfully merged)
            deleted_count = 0
            for segment in valid_segments:
                try:
                    segment.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.warning(
                        f"[{self.name}] Failed to delete segment {segment.name}: {e}"
                    )

            logger.debug(
                f"[{self.name}] Deleted {deleted_count}/{len(valid_segments)} merged segments"
            )

            return True

        except subprocess.TimeoutExpired:
            logger.error(f"[{self.name}] FFmpeg merge timed out")
            return False
        except Exception as e:
            logger.error(f"[{self.name}] Error during merge: {e}", exc_info=True)
            return False
        finally:
            # Clean up filelist
            try:
                filelist_path.unlink()
            except Exception:
                pass

    def _merge_old_segments(self) -> None:
        """Find and merge segments older than merge_delay"""
        if not self.segments_dir.exists():
            return

        # Calculate cutoff time
        cutoff_time = datetime.now() - timedelta(seconds=self.merge_delay)
        cutoff_timestamp = cutoff_time.timestamp()

        # Find all segments older than cutoff
        old_segments = []
        for segment_file in self.segments_dir.glob("*.mp4"):
            try:
                # Check file modification time
                file_mtime = segment_file.stat().st_mtime
                if file_mtime < cutoff_timestamp:
                    old_segments.append(segment_file)
            except Exception as e:
                logger.warning(
                    f"[{self.name}] Error checking segment {segment_file.name}: {e}"
                )

        if not old_segments:
            logger.debug(f"[{self.name}] No old segments to merge")
            return

        # Group by minute
        groups = self._group_segments_by_minute(old_segments)

        # Merge each group
        merged_count = 0
        for time_key, segments in groups.items():
            # 只合併「該分鐘的最後一秒 < cutoff_time」的分鐘
            # 例如：time_key = '20251108_1627'，檢查 16:27:59 是否 < cutoff_time
            minute_end = datetime.strptime(time_key, "%Y%m%d_%H%M")
            minute_end = minute_end.replace(second=59)

            if minute_end.timestamp() >= cutoff_timestamp:
                logger.debug(
                    f"[{self.name}] Skipping incomplete minute: {time_key} "
                    f"(end time {minute_end.strftime('%H:%M:%S')} >= {datetime.fromtimestamp(cutoff_timestamp).strftime('%H:%M:%S')})"
                )
                continue

            # Output filename: YYYYMMDD_HHMM.mp4
            output_filename = f"{time_key}.mp4"
            output_path = self.merged_dir / output_filename

            # Skip if already merged
            if output_path.exists():
                logger.debug(
                    f"[{self.name}] Merged file already exists: {output_filename}, "
                    f"deleting {len(segments)} segments"
                )
                # Delete segments even if merged file exists (recovery case)
                for segment in segments:
                    try:
                        segment.unlink()
                    except Exception:
                        pass
                continue

            if self._merge_segments(segments, output_path):
                merged_count += 1

        if merged_count > 0:
            logger.info(f"[{self.name}] Merged {merged_count} group(s) of segments")

    def _run_aggregator(self) -> None:
        """Run aggregator periodically"""
        logger.info(
            f"[{self.name}] Aggregator started: interval={self.merge_interval}s, "
            f"delay={self.merge_delay}s"
        )

        while not self._stop_event.is_set():
            try:
                self._merge_old_segments()
            except Exception as e:
                logger.error(f"[{self.name}] Error in aggregator: {e}", exc_info=True)

            # Wait for next merge interval
            self._stop_event.wait(self.merge_interval)

    def start(self) -> None:
        """Start aggregator in a separate thread"""
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"[{self.name}] Aggregator already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_aggregator, daemon=True)
        self._thread.start()
        logger.info(f"[{self.name}] Aggregator thread started")

    def stop(self) -> None:
        """Stop aggregator gracefully"""
        logger.info(f"[{self.name}] Stopping aggregator...")
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=10)

        logger.info(f"[{self.name}] Aggregator stopped")

    def is_running(self) -> bool:
        """Check if aggregator is running"""
        return self._thread is not None and self._thread.is_alive()
