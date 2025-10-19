'''RTSP stream recorder using FFmpeg'''

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class CameraRecorder:
    '''Records RTSP stream from a single camera using FFmpeg'''
    
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
        self.output_dir = Path(output_dir)
        self.segment_duration = segment_duration
        self.reconnect_delay = reconnect_delay
        self.ffmpeg_options = ffmpeg_options
        
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _build_ffmpeg_command(self) -> list[str]:
        '''Build FFmpeg command with all required parameters'''

        output_pattern = str(self.output_dir / "%Y%m%d_%H%M%S.mp4")
        return [
            'ffmpeg',
            '-rtsp_transport', 'tcp',
            '-rtbufsize', self.ffmpeg_options.get('rtbufsize', '100M'),
            '-timeout', str(self.ffmpeg_options.get('timeout', 5000000)),
            '-use_wallclock_as_timestamps', '1',
            '-i', self.rtsp_url,
            '-reset_timestamps', '1',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-f', 'segment',
            '-segment_time', str(self.segment_duration),
            '-segment_format', 'mp4',
            '-strftime', '1',
            output_pattern,
        ]

    
    def _run_ffmpeg(self) -> None:
        '''Run FFmpeg process with auto-reconnect'''
        while not self._stop_event.is_set():
            try:
                cmd = self._build_ffmpeg_command()
                logger.info(f'[{self.name}] Starting FFmpeg recording...')
                logger.debug(f'[{self.name}] Command: {" ".join(cmd)}')
                
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                
                # Monitor the process
                while not self._stop_event.is_set():
                    if self._process.poll() is not None:
                        # Process has ended
                        stdout, stderr = self._process.communicate()
                        logger.warning(
                            f'[{self.name}] FFmpeg process ended. '
                            f'Return code: {self._process.returncode}'
                        )
                        if stderr:
                            logger.debug(f'[{self.name}] FFmpeg stderr: {stderr[-500:]}')
                        break
                    time.sleep(1)
                
                # If we're not stopping, wait before reconnecting
                if not self._stop_event.is_set():
                    logger.info(
                        f'[{self.name}] Reconnecting in {self.reconnect_delay} seconds...'
                    )
                    self._stop_event.wait(self.reconnect_delay)
                
            except Exception as e:
                logger.error(f'[{self.name}] Error in recording: {e}', exc_info=True)
                if not self._stop_event.is_set():
                    logger.info(
                        f'[{self.name}] Retrying in {self.reconnect_delay} seconds...'
                    )
                    self._stop_event.wait(self.reconnect_delay)
    
    def start(self) -> None:
        '''Start recording in a separate thread'''
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f'[{self.name}] Recorder already running')
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_ffmpeg, daemon=True)
        self._thread.start()
        logger.info(f'[{self.name}] Recorder started')
    
    def stop(self) -> None:
        '''Stop recording gracefully'''
        logger.info(f'[{self.name}] Stopping recorder...')
        self._stop_event.set()
        
        # Terminate FFmpeg process
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f'[{self.name}] FFmpeg did not terminate, killing...')
                self._process.kill()
        
        # Wait for thread to finish
        if self._thread is not None:
            self._thread.join(timeout=10)
        
        logger.info(f'[{self.name}] Recorder stopped')
    
    def is_running(self) -> bool:
        '''Check if recorder is running'''
        return self._thread is not None and self._thread.is_alive()

