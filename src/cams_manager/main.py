"""Main entry point for cams-manager"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from .aggregator import SegmentAggregator
from .cleaner import RecordingCleaner
from .config import Config
from .recorder import CameraRecorder


logger = logging.getLogger(__name__)


class CamsManager:
    """Main application class for managing multiple camera recorders"""

    def __init__(self, config_path: str | Path):
        self.config = Config.from_yaml(config_path)
        self.recorders: list[CameraRecorder] = []
        self.aggregators: list[SegmentAggregator] = []
        self.cleaner: RecordingCleaner | None = None
        self._shutdown = False

    def setup_recorders(self) -> None:
        """Initialize recorders for all cameras"""
        for camera in self.config.cameras:
            recorder = CameraRecorder(
                name=camera.name,
                rtsp_url=camera.rtsp_url,
                output_dir=camera.output_dir,
                segment_duration=self.config.recording.segment_duration,
                reconnect_delay=self.config.recording.reconnect_delay,
                ffmpeg_options=self.config.ffmpeg.model_dump(),
            )
            self.recorders.append(recorder)

        logger.info(f"Initialized {len(self.recorders)} camera recorders")

    def setup_aggregators(self) -> None:
        """Initialize aggregators for all cameras"""
        for camera in self.config.cameras:
            base_dir = Path(camera.output_dir)
            segments_dir = base_dir / "segments"
            merged_dir = base_dir / "merged"

            aggregator = SegmentAggregator(
                name=camera.name,
                segments_dir=segments_dir,
                merged_dir=merged_dir,
                merge_interval=self.config.recording.merge_interval,
                merge_delay=self.config.recording.merge_delay,
            )
            self.aggregators.append(aggregator)

        logger.info(f"Initialized {len(self.aggregators)} segment aggregators")

    def setup_cleaner(self) -> None:
        """Initialize cleaner for old recordings"""
        recording_dirs = [Path(cam.output_dir) for cam in self.config.cameras]
        self.cleaner = RecordingCleaner(
            recording_dirs=recording_dirs,
            retention_days=self.config.recording.retention_days,
            merge_delay=self.config.recording.merge_delay,
        )
        logger.info("Initialized recording cleaner")

    def start(self) -> None:
        """Start all recorders and cleaner"""
        logger.info("Starting cams-manager...")

        # Start all recorders
        for recorder in self.recorders:
            recorder.start()

        # Start all aggregators
        for aggregator in self.aggregators:
            aggregator.start()

        # Start cleaner
        if self.cleaner:
            self.cleaner.start()

        logger.info("All services started successfully")

    def stop(self) -> None:
        """Stop all recorders and cleaner"""
        if self._shutdown:
            return

        self._shutdown = True
        logger.info("Shutting down cams-manager...")

        # Stop all recorders
        for recorder in self.recorders:
            recorder.stop()

        # Stop all aggregators
        for aggregator in self.aggregators:
            aggregator.stop()

        # Stop cleaner
        if self.cleaner:
            self.cleaner.stop()

        logger.info("All services stopped")

    def run(self) -> None:
        """Run the application until interrupted"""
        # Setup signal handlers
        signal.signal(signal.SIGTERM, lambda sig, frame: self.stop())
        signal.signal(signal.SIGINT, lambda sig, frame: self.stop())

        # Setup and start services
        self.setup_recorders()
        self.setup_aggregators()
        self.setup_cleaner()
        self.start()

        # Keep running until shutdown
        try:
            while not self._shutdown:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            self.stop()


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration"""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="IP Camera RTSP Stream Recorder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)

    # Check if config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        logger.info(
            "Please create a config.yaml file. See config.yaml.example for reference."
        )
        sys.exit(1)

    # Run application
    try:
        manager = CamsManager(config_path)
        manager.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
