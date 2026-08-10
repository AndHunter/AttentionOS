"""Feature schema — versioned definition of all engineered features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class FeatureDefinition:
    """Metadata for a single feature."""

    name: str
    group: str
    dtype: Literal["float", "int", "bool"]
    description: str
    window_minutes: int | None = None  # None means no windowing


# All features defined in the pipeline
FEATURE_DEFINITIONS: list[FeatureDefinition] = [
    # --- Focus group ---
    FeatureDefinition(
        "mean_focus_block_sec",
        "focus",
        "float",
        "Mean focus block duration (seconds).",
    ),
    FeatureDefinition(
        "max_focus_block_sec",
        "focus",
        "float",
        "Max focus block duration (seconds).",
    ),
    FeatureDefinition(
        "uninterrupted_ratio",
        "focus",
        "float",
        "Ratio of focus time to total time.",
    ),

    # --- Switching group ---
    FeatureDefinition("switches_15m", "switching", "int", "Context switches in last 15 min.", 15),
    FeatureDefinition("switches_30m", "switching", "int", "Context switches in last 30 min.", 30),
    FeatureDefinition("switches_60m", "switching", "int", "Context switches in last 60 min.", 60),
    FeatureDefinition("unique_apps", "switching", "int", "Unique applications used."),
    FeatureDefinition(
        "switch_entropy",
        "switching",
        "float",
        "Shannon entropy of app time distribution.",
    ),

    # --- Idle group ---
    FeatureDefinition("idle_ratio", "idle", "float", "Ratio of idle time to total time."),
    FeatureDefinition("idle_bursts", "idle", "int", "Count of idle bursts (transitions to idle)."),
    FeatureDefinition(
        "time_since_last_break_min",
        "idle",
        "float",
        "Minutes since last idle period >= 5 min.",
    ),

    # --- Input dynamics ---
    FeatureDefinition("keyboard_rate", "input", "float", "Keyboard events per minute."),
    FeatureDefinition("mouse_rate", "input", "float", "Mouse events per minute."),
    FeatureDefinition(
        "kb_rate_change_pct",
        "input",
        "float",
        "Keyboard rate change vs session average (%).",
    ),
    FeatureDefinition(
        "mouse_rate_change_pct",
        "input",
        "float",
        "Mouse rate change vs session average (%).",
    ),

    # --- Temporal ---
    FeatureDefinition("hour_of_day", "temporal", "int", "Hour of day (0-23)."),
    FeatureDefinition("weekday", "temporal", "int", "Day of week (0=Mon, 6=Sun)."),
    FeatureDefinition(
        "session_age_min",
        "temporal",
        "float",
        "Minutes since current work session started.",
    ),
    FeatureDefinition(
        "work_since_day_start_min",
        "temporal",
        "float",
        "Active minutes since first event today.",
    ),

    # --- Workload ---
    FeatureDefinition(
        "active_minutes_2h",
        "workload",
        "float",
        "Active minutes in last 2 hours.",
        120,
    ),
    FeatureDefinition("active_minutes_day", "workload", "float", "Total active minutes today."),
    FeatureDefinition(
        "previous_session_length_min",
        "workload",
        "float",
        "Duration of the previous session (minutes).",
    ),

    # --- Task ---
    FeatureDefinition("task_label_encoded", "task", "int", "Encoded task label (ordinal)."),
]


def get_feature_names() -> list[str]:
    """Return a list of all feature names in schema order."""
    return [f.name for f in FEATURE_DEFINITIONS]


def get_feature_groups() -> dict[str, list[str]]:
    """Return features grouped by category."""
    groups: dict[str, list[str]] = {}
    for f in FEATURE_DEFINITIONS:
        groups.setdefault(f.group, []).append(f.name)
    return groups
