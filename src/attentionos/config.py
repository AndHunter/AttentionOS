"""Application configuration with environment and file overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    """Return the platform-specific user data directory for AttentionOS."""
    app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA", ".")
    return Path(app_data) / "AttentionOS"


class CollectorConfig(BaseSettings):
    """Telemetry collector settings."""

    polling_interval_sec: float = Field(
        default=3.0,
        ge=1.0,
        le=10.0,
        description="How often (seconds) to poll foreground window and idle state.",
    )
    idle_threshold_sec: float = Field(
        default=120.0,
        ge=30.0,
        description="Seconds of no input before a period is considered idle.",
    )
    batch_size: int = Field(
        default=20,
        ge=1,
        description="Number of events to accumulate before flushing to DB.",
    )
    batch_flush_interval_sec: float = Field(
        default=30.0,
        ge=5.0,
        description="Maximum seconds between DB flushes, even if batch is not full.",
    )
    store_window_titles: bool = Field(
        default=False,
        description="If False, only process_name is stored. Titles are hashed if True.",
    )


class SelfReportConfig(BaseSettings):
    """Self-report prompt settings."""

    prompt_interval_min: int = Field(
        default=45,
        ge=10,
        description="Minutes between self-report prompts.",
    )
    effectiveness_scale: tuple[int, int] = (1, 5)
    fatigue_scale: tuple[int, int] = (1, 5)
    default_task_labels: list[str] = Field(
        default=[
            "Coding",
            "ML",
            "Math",
            "English",
            "Rest",
            "Meeting",
            "Admin",
            "Other",
        ]
    )


class InterventionConfig(BaseSettings):
    """Intervention engine settings."""

    risk_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum predicted risk to trigger an alert.",
    )
    confidence_threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Minimum model confidence to trigger an alert.",
    )
    cooldown_minutes: int = Field(
        default=30,
        ge=5,
        description="Minimum minutes between consecutive alerts.",
    )
    default_break_duration_min: int = Field(
        default=20,
        ge=5,
        description="Default recommended break duration in minutes.",
    )


class AppConfig(BaseSettings):
    """Root application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ATTENTIONOS_",
        env_nested_delimiter="__",
        toml_file="config.toml",
    )

    # --- Paths ---
    data_dir: Path = Field(default_factory=_default_data_dir)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- Sub-configs ---
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    self_report: SelfReportConfig = Field(default_factory=SelfReportConfig)
    intervention: InterventionConfig = Field(default_factory=InterventionConfig)

    # --- Derived ---
    collector_version: str = "0.1.0"

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self.data_dir / "attentionos.db"

    @property
    def log_path(self) -> Path:
        """Path to the log file."""
        return self.data_dir / "attentionos.log"

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "exports").mkdir(exist_ok=True)


def get_config() -> AppConfig:
    """Load and return the application configuration."""
    config = AppConfig()
    config.ensure_dirs()
    return config
