"""RTSP stream recorder using FFmpeg"""

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class CameraRecorder:
    """Records RTSP stream from a single camera using FFmpeg"""

    PERIODIC_RESTART_INTERVAL = 18 * 60  # 18 minutes
    HEALTH_CHECK_INTERVAL = 5  # Check health every 5 seconds

    def __init__(
        self,
        name: str,
        rtsp_url: str,
        output_dir: str | Path,
        segment_duration: int,
        reconnect_delay: int,
        ffmpeg_options: dict[str, Any],
    ):
        self.name = name
        self.rtsp_url = rtsp_url
        self.base_output_dir = Path(output_dir)
        # 輸出到 segments 子目錄
        self.output_dir = self.base_output_dir / "segments"
        self.segment_duration = segment_duration
        self.reconnect_delay = reconnect_delay
        self.ffmpeg_options = ffmpeg_options

        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _build_ffmpeg_command(self) -> list[str]:
        """Build FFmpeg command with all required parameters"""

        output_pattern = str(self.output_dir / "%Y%m%d_%H%M%S.mp4")
        return [
            "ffmpeg",
            "-nostdin",  # Don't read from stdin (prevents hanging in background)
            "-rtsp_transport",
            "tcp",
            "-rtbufsize",
            self.ffmpeg_options.get("rtbufsize", "100M"),
            "-timeout",
            str(self.ffmpeg_options.get("timeout", 5000000)),
            # Note: reconnect options are deprecated in newer FFmpeg versions
            # Reconnection is handled by our health check mechanism instead
            "-use_wallclock_as_timestamps",
            "1",
            "-i",
            self.rtsp_url,
            "-reset_timestamps",
            "1",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-f",
            "segment",
            # 在整點時間切換 segment
            "-segment_atclocktime",
            "1",
            "-segment_clocktime_offset",
            "0",
            "-segment_time",
            str(self.segment_duration),
            "-segment_time_delta",
            "0.05",
            "-segment_format",
            "mp4",
            "-strftime",
            "1",
            # 避免時間戳問題
            "-avoid_negative_ts",
            "make_zero",
            # 增加 muxing 佇列
            "-max_muxing_queue_size",
            "1024",
            output_pattern,
        ]

    def _get_latest_segment_mtime(self) -> float | None:
        """Get modification time of the latest segment file"""
        if not self.output_dir.exists():
            return None

        segments = list(self.output_dir.glob("*.mp4"))
        if not segments:
            return None

        # Get the most recently modified file
        latest = max(segments, key=lambda p: p.stat().st_mtime)
        return latest.stat().st_mtime

    def _check_ffmpeg_health(self, timeout: int) -> bool:
        """Check if FFmpeg is producing new files (health check)"""
        if self._process is None or self._process.poll() is not None:
            return False

        # Check if new files are being created
        # Allow up to segment_duration * 3 seconds without new files before considering it hung
        latest_mtime = self._get_latest_segment_mtime()

        if latest_mtime is None:
            # No files yet, give it some time
            return True

        time_since_last_file = time.time() - latest_mtime
        if time_since_last_file > timeout:
            logger.warning(
                f"[{self.name}] FFmpeg appears to be hung: "
                f"no new files for {time_since_last_file:.1f} seconds "
                f"(threshold: {timeout}s)"
            )
            return False

        return True

    def _terminate_process(self, reason: str = "terminating") -> None:
        """Terminate FFmpeg process gracefully, with fallback to kill if needed"""
        if self._process is None:
            return

        if self._process.poll() is not None:
            # Process already ended
            return

        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"[{self.name}] FFmpeg did not terminate, killing...")
                self._process.kill()
                self._process.wait()
        except Exception as e:
            logger.error(f"[{self.name}] Error {reason} FFmpeg process: {e}")

    def _run_ffmpeg(self) -> None:
        """Run FFmpeg process with auto-reconnect and health monitoring"""
        while not self._stop_event.is_set():
            try:
                cmd = self._build_ffmpeg_command()
                logger.info(f"[{self.name}] Starting FFmpeg recording...")
                logger.debug(f"[{self.name}] Command: {' '.join(cmd)}")

                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,  # Prevent stdin from causing hangs
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                # Track process start time for periodic restart (19 min 50 sec = 1190 seconds)
                # This prevents RTSP session timeout issues (typically 20 minutes)
                process_start_time = time.time()

                # Track last health check time
                last_health_check = time.time()

                wait_for_reconnect = True

                # Monitor the process
                while not self._stop_event.is_set():
                    if self._process.poll() is not None:
                        # Process has ended
                        stdout, stderr = self._process.communicate()
                        logger.warning(
                            f"[{self.name}] FFmpeg process ended. "
                            f"Return code: {self._process.returncode}"
                        )
                        if stderr:
                            logger.debug(
                                f"[{self.name}] FFmpeg stderr: {stderr[-500:]}"
                            )
                        break

                    current_time = time.time()

                    # Check if it's time for periodic restart (before RTSP session timeout)
                    process_runtime = current_time - process_start_time
                    if process_runtime >= self.PERIODIC_RESTART_INTERVAL:
                        logger.info(
                            f"[{self.name}] Periodic restarting: {process_runtime:.1f}/{self.PERIODIC_RESTART_INTERVAL:.1f} seconds"
                        )
                        self._terminate_process("periodic restart")
                        wait_for_reconnect = False
                        break

                    # Periodic health check
                    if current_time - last_health_check >= self.HEALTH_CHECK_INTERVAL:
                        if not self._check_ffmpeg_health(
                            self.HEALTH_CHECK_INTERVAL * 2
                        ):
                            # FFmpeg appears to be hung, force restart
                            logger.warning(
                                f"[{self.name}] FFmpeg health check failed, "
                                f"forcing restart..."
                            )
                            self._terminate_process("health check failure")
                            wait_for_reconnect = False
                            break
                        last_health_check = current_time

                    time.sleep(1)

                # If we're not stopping, wait before reconnecting
                if not self._stop_event.is_set() and wait_for_reconnect:
                    logger.info(
                        f"[{self.name}] Reconnecting in {self.reconnect_delay} seconds..."
                    )
                    self._stop_event.wait(self.reconnect_delay)

            except Exception as e:
                logger.error(f"[{self.name}] Error in recording: {e}", exc_info=True)
                if not self._stop_event.is_set():
                    logger.info(
                        f"[{self.name}] Retrying in {self.reconnect_delay} seconds..."
                    )
                    self._stop_event.wait(self.reconnect_delay)

    def start(self) -> None:
        """Start recording in a separate thread"""
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"[{self.name}] Recorder already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_ffmpeg, daemon=True)
        self._thread.start()
        logger.info(f"[{self.name}] Recorder started")

    def stop(self) -> None:
        """Stop recording gracefully"""
        logger.info(f"[{self.name}] Stopping recorder...")
        self._stop_event.set()

        # Terminate FFmpeg process
        self._terminate_process("stopping recorder")

        # Wait for thread to finish
        if self._thread is not None:
            self._thread.join(timeout=10)

        logger.info(f"[{self.name}] Recorder stopped")

    def is_running(self) -> bool:
        """Check if recorder is running"""
        return self._thread is not None and self._thread.is_alive()
