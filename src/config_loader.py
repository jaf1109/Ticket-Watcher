"""Load and validate config.yaml."""

from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel, field_validator
import yaml


class MovieConfig(BaseModel):
    name: str = ""
    id: str | int | None = None


class CinemaConfig(BaseModel):
    location: str = ""
    location_id: str | int | None = None
    name: str = ""
    id: str | int | None = None


class MonitoringConfig(BaseModel):
    interval_seconds: int = 60
    max_duration_minutes: int = 0
    max_consecutive_errors: int = 10
    fallback_to_browser: bool = True

    @field_validator("interval_seconds")
    @classmethod
    def min_interval(cls, v: int) -> int:
        if v < 30:
            return 30
        return v


class DesktopNotifConfig(BaseModel):
    enabled: bool = True


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class NotificationsConfig(BaseModel):
    desktop: DesktopNotifConfig = DesktopNotifConfig()
    telegram: TelegramConfig = TelegramConfig()


class LoggingConfig(BaseModel):
    level: str = "INFO"


class Config(BaseModel):
    movie: MovieConfig = MovieConfig()
    cinema: CinemaConfig = CinemaConfig()
    monitoring: MonitoringConfig = MonitoringConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    logging: LoggingConfig = LoggingConfig()


def load_config(path: str | Path | None = None) -> Config:
    """Load config from YAML file with env var overrides for secrets."""
    if path is None:
        path = Path(__file__).parent.parent / "config.yaml"
    path = Path(path)

    if not path.exists():
        return Config()

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    config = Config(**data)

    # Environment variable overrides for secrets
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        config.notifications.telegram.bot_token = token
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if chat_id:
        config.notifications.telegram.chat_id = chat_id

    return config


def save_config(config: Config, path: str | Path | None = None) -> None:
    """Save config back to YAML."""
    if path is None:
        path = Path(__file__).parent.parent / "config.yaml"
    path = Path(path)

    data = config.model_dump()
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
