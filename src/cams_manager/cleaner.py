"""Old recording files cleaner"""

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path


logger = logging.getLogger(__name__)


class RecordingCleaner:
    """Periodically cleans old recording files"""

    def __init__(
        self,
        recording_dirs: list[Path],
        retention_days: int,
        merge_delay: int = 120,
        check_interval: int = 3600,  # 1 hour
    ):
        self.recording_dirs = recording_dirs
        self.retention_days = retention_days
        self.merge_delay = merge_delay
        self.check_interval = check_interval

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def _parse_segment_time_key(self, filename: str) -> str | None:
        """Extract time key (YYYYMMDD_HHMM) from segment filename"""
        try:
            # Remove extension
            name_without_ext = filename.rsplit(".", 1)[0]
            # Parse datetime
            dt = datetime.strptime(name_without_ext, "%Y%m%d_%H%M%S")
            # Return minute-level key
            return dt.strftime("%Y%m%d_%H%M")
        except ValueError:
            return None

    def _clean_old_files(self) -> None:
        """Remove files older than retention period"""
        cutoff_time = datetime.now() - timedelta(days=self.retention_days)
        cutoff_timestamp = cutoff_time.timestamp()

        total_deleted = 0
        total_freed = 0

        for recording_dir in self.recording_dirs:
            if not recording_dir.exists():
                logger.warning(f"Recording directory does not exist: {recording_dir}")
                continue

            merged_dir = recording_dir / "merged"
            segments_dir = recording_dir / "segments"

            # Clean merged files
            if merged_dir.exists():
                logger.debug(f"Scanning merged directory: {merged_dir}")
                for file_path in merged_dir.glob("*.mp4"):
                    try:
                        file_mtime = file_path.stat().st_mtime
                        if file_mtime < cutoff_timestamp:
                            file_size = file_path.stat().st_size
                            file_path.unlink()
                            total_deleted += 1
                            total_freed += file_size
                            logger.info(
                                f"Deleted old merged file: {file_path.name} "
                                f"(size: {file_size / 1024 / 1024:.2f} MB)"
                            )
                    except Exception as e:
                        logger.error(f"Error deleting file {file_path}: {e}")

            # Clean segments only if corresponding merged file exists
            if segments_dir.exists() and merged_dir.exists():
                logger.debug(f"Scanning segments directory: {segments_dir}")

                # Build set of existing merged files (without extension)
                merged_files = {f.stem for f in merged_dir.glob("*.mp4")}

                for file_path in segments_dir.glob("*.mp4"):
                    try:
                        # Get the time key for this segment
                        time_key = self._parse_segment_time_key(file_path.name)
                        if time_key is None:
                            logger.warning(
                                f"Cannot parse segment filename: {file_path.name}"
                            )
                            continue

                        # Only delete if corresponding merged file exists
                        if time_key in merged_files:
                            file_size = file_path.stat().st_size
                            file_path.unlink()
                            total_deleted += 1
                            total_freed += file_size
                            logger.debug(
                                f"Deleted merged segment: {file_path.name} "
                                f"(merged file exists: {time_key}.mp4)"
                            )
                        else:
                            # Check if segment is very old (potential orphan)
                            file_mtime = file_path.stat().st_mtime
                            orphan_cutoff = datetime.now() - timedelta(days=1)
                            if file_mtime < orphan_cutoff.timestamp():
                                logger.warning(
                                    f"Found old unmerged segment: {file_path.name} "
                                    f"(no corresponding merged file)"
                                )
                    except Exception as e:
                        logger.error(f"Error processing segment {file_path}: {e}")

        if total_deleted > 0:
            logger.info(
                f"Cleanup completed: {total_deleted} files deleted, "
                f"{total_freed / 1024 / 1024 / 1024:.2f} GB freed"
            )
        else:
            logger.debug("No old files to clean")

    def _run_cleaner(self) -> None:
        """Run cleaner periodically"""
        logger.info(
            f"Cleaner started: checking every {self.check_interval}s, "
            f"retention: {self.retention_days} days"
        )

        while not self._stop_event.is_set():
            try:
                self._clean_old_files()
            except Exception as e:
                logger.error(f"Error in cleaner: {e}", exc_info=True)

            # Wait for next check interval
            self._stop_event.wait(self.check_interval)

    def start(self) -> None:
        """Start cleaner in a separate thread"""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Cleaner already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_cleaner, daemon=True)
        self._thread.start()
        logger.info("Cleaner thread started")

    def stop(self) -> None:
        """Stop cleaner gracefully"""
        logger.info("Stopping cleaner...")
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=5)

        logger.info("Cleaner stopped")

    def is_running(self) -> bool:
        """Check if cleaner is running"""
        return self._thread is not None and self._thread.is_alive()
