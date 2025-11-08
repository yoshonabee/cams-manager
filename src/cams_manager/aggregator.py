"""Segment aggregator for merging short segments into longer files"""

import logging
import subprocess
import tempfile
import threading
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

        # Create temporary file list
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            filelist_path = Path(f.name)
            for segment in segments:
                # Use absolute path and escape single quotes
                abs_path = segment.resolve()
                f.write(f"file '{abs_path}'\n")

        try:
            # Use temporary output file first (atomic write)
            temp_output = output_path.with_suffix(".tmp")

            # Build FFmpeg command
            cmd = [
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(filelist_path),
                "-c",
                "copy",  # Copy codec, no re-encoding
                "-y",  # Overwrite output file
                str(temp_output),
            ]

            logger.debug(
                f"[{self.name}] Merging {len(segments)} segments into {output_path.name}"
            )

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
                    f"[{self.name}] FFmpeg merge failed: {result.stderr[-500:]}"
                )
                # Clean up temp file
                if temp_output.exists():
                    temp_output.unlink()
                return False

            # Atomic rename
            temp_output.rename(output_path)
            logger.info(
                f"[{self.name}] Successfully merged {len(segments)} segments "
                f"into {output_path.name}"
            )

            # Delete merged segments
            deleted_count = 0
            for segment in segments:
                try:
                    segment.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.warning(
                        f"[{self.name}] Failed to delete segment {segment.name}: {e}"
                    )

            logger.debug(
                f"[{self.name}] Deleted {deleted_count}/{len(segments)} segments"
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
                    f"(end time {minute_end.strftime('%H:%M:%S')} >= cutoff)"
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
