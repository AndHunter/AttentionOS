"""JSON-backed runtime settings.

These settings are intentionally separate from AppConfig. AppConfig describes
installation/runtime paths; RuntimeSettings stores user preferences changed from
the desktop app.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

LanguageMode = Literal["system", "en", "ru"]
ThemeMode = Literal["system", "light", "dark"]


class UserPreferences(BaseModel):
    """General desktop preferences."""

    language: LanguageMode = "system"
    theme: ThemeMode = "system"
    launch_on_startup: bool = False
    minimize_to_tray: bool = False
    start_minimized: bool = False
    current_task_label: str = "None"


class TrackingSettings(BaseModel):
    """Privacy-sensitive telemetry toggles."""

    idle_threshold_minutes: int = Field(default=5, ge=1, le=30)
    track_active_window: bool = True
    track_window_titles: bool = False
    track_keyboard_activity: bool = True
    track_mouse_activity: bool = True
    excluded_applications: list[str] = Field(default_factory=list)


class NotificationSettings(BaseModel):
    """Notification behavior. Predictive warnings stay off until a model exists."""

    break_recommendations: bool = True
    performance_warnings: bool = False
    minimum_interval_minutes: int = Field(default=30, ge=15, le=60)
    do_not_disturb_start: str = "23:00"
    do_not_disturb_end: str = "08:00"


class ModelSettings(BaseModel):
    """Model readiness thresholds."""

    min_training_samples: int = Field(default=30, ge=5)


class RuntimeSettings(BaseModel):
    """All user-editable settings."""

    preferences: UserPreferences = Field(default_factory=UserPreferences)
    tracking: TrackingSettings = Field(default_factory=TrackingSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    model: ModelSettings = Field(default_factory=ModelSettings)


class SettingsStore:
    """Load and save RuntimeSettings as JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RuntimeSettings:
        if not self.path.exists():
            return RuntimeSettings()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return RuntimeSettings.model_validate(data)
        except Exception:
            return RuntimeSettings()

    def save(self, settings: RuntimeSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(settings.model_dump(), handle, indent=2, ensure_ascii=False)
