"""Configuration loader for cams-manager"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Camera(BaseModel, extra="forbid"):
    """Camera configuration model"""

    name: str
    rtsp_url: str
    output_dir: str


class Recording(BaseModel):
    """Recording configuration model"""

    segment_duration: int = Field(default=60, description="Segment duration in seconds")
    retention_days: int = Field(default=7, description="Retention period in days")
    reconnect_delay: int = Field(default=5, description="Reconnect delay in seconds")


class FFmpeg(BaseModel):
    """FFmpeg configuration model"""

    rtbufsize: str = Field(default="100M", description="RT buffer size")
    timeout: int = Field(default=5000000, description="Stream timeout in microseconds")
    rw_timeout: int = Field(
        default=5000000, description="Read/write timeout in microseconds"
    )


class Config(BaseSettings):
    """Configuration class using pydantic settings"""

    model_config = SettingsConfigDict(
        env_prefix="CAMS_",
        env_nested_delimiter="__",
    )

    cameras: list[Camera] = Field(
        default_factory=list, description="List of camera configurations"
    )
    recording: Recording = Field(
        default_factory=Recording, description="Recording settings"
    )
    ffmpeg: FFmpeg = Field(default_factory=FFmpeg, description="FFmpeg settings")

    @classmethod
    def from_yaml(cls, config_path: str | Path) -> "Config":
        """Load configuration from YAML file"""
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with config_path.open() as f:
            data = yaml.safe_load(f)

        return cls.model_validate(data)
