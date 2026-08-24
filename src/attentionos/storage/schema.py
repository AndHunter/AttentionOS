"""Database schema — SQLModel table definitions for all core entities."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlmodel import Field, SQLModel

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InterventionType(enum.StrEnum):
    """Types of recommended interventions."""

    BREAK_10 = "break_10"
    BREAK_20 = "break_20"
    CONTINUE = "continue"
    SWITCH_TASK = "switch_task"


class NotificationState(enum.StrEnum):
    """Lifecycle state for in-app notifications."""

    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"


class InterventionResponse(enum.StrEnum):
    """User response to a recommendation."""

    STARTED = "started"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"


class ReasonCode(enum.StrEnum):
    """Why the intervention was triggered."""

    SWITCHING = "switching"
    LONG_SESSION = "long_session"
    UNUSUAL_IDLE = "unusual_idle"
    BASELINE_DEVIATION = "baseline_deviation"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class ActivityEvent(SQLModel, table=True):
    """A single telemetry snapshot captured by the collector.

    Each row represents one polling interval (typically 3 seconds).
    No raw keystroke content is ever stored — only aggregate counts.
    """

    __tablename__ = "activity_events"

    id: int | None = Field(default=None, primary_key=True)

    ts_start: datetime = Field(index=True, description="Start of the observation window.")
    ts_end: datetime = Field(description="End of the observation window.")

    process_name: str = Field(
        max_length=256,
        description="Executable name of the foreground process (e.g. 'code.exe').",
    )
    window_title_hash: str | None = Field(
        default=None,
        max_length=64,
        description="SHA-256 hash of the window title (privacy-safe). NULL if disabled.",
    )

    idle_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Seconds since last user input at observation time.",
    )

    keyboard_events: int = Field(
        default=0,
        ge=0,
        description="Count of keyboard events in this interval.",
    )
    mouse_events: int = Field(
        default=0,
        ge=0,
        description="Count of mouse events (clicks + movement deltas) in this interval.",
    )

    task_label: str | None = Field(
        default=None,
        max_length=64,
        description="User-assigned task category (e.g. 'Coding', 'ML', 'Rest').",
    )

    collector_version: str = Field(
        default="0.5.0",
        max_length=16,
        description="Version of the collector that produced this event.",
    )


class SelfReport(SQLModel, table=True):
    """User's self-assessment of perceived effectiveness and fatigue.

    Collected periodically (default: every 45 minutes) via UI prompt.
    """

    __tablename__ = "self_reports"

    id: int | None = Field(default=None, primary_key=True)

    timestamp: datetime = Field(index=True)
    task_name: str | None = Field(
        default=None,
        max_length=64,
        description="Task label selected when the report was created.",
    )
    telemetry_window_start: datetime | None = Field(
        default=None,
        index=True,
        description="Start of the telemetry window used for supervised features.",
    )
    telemetry_window_end: datetime | None = Field(
        default=None,
        index=True,
        description="End of the telemetry window used for supervised features.",
    )

    perceived_effectiveness: int = Field(
        ge=1, le=5, description="Self-rated effectiveness 1 (very low) to 5 (very high)."
    )
    perceived_fatigue: int = Field(
        ge=1, le=5, description="Self-rated fatigue 1 (very low) to 5 (very high)."
    )
    task_difficulty: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Optional perceived difficulty of current task.",
    )
    note: str | None = Field(
        default=None,
        max_length=500,
        description="Optional free-text note.",
    )
    prompt_reason: str = Field(
        default="MANUAL",
        max_length=32,
        description="Why the report was requested: MANUAL, POST_BREAK, IGNORED_RECOMMENDATION, etc.",
    )


class Intervention(SQLModel, table=True):
    """A recommendation made by the intervention engine and user's response."""

    __tablename__ = "interventions"

    id: int | None = Field(default=None, primary_key=True)

    timestamp: datetime = Field(index=True)

    type: InterventionType = Field(description="What was recommended.")
    reason_code: ReasonCode | None = Field(
        default=None, description="Why the intervention was triggered."
    )

    pre_state: str | None = Field(
        default=None,
        description="JSON snapshot of the state before the intervention.",
    )
    post_report_id: int | None = Field(
        default=None,
        foreign_key="self_reports.id",
        description="Optional self-report collected after the intervention.",
    )
    predicted_state: float = Field(
        default=0.0,
        description="Model's predicted state score at the time of recommendation."
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Model's confidence in the prediction."
    )

    accepted: bool = Field(default=False, description="Whether the user accepted it.")
    completed: bool = Field(default=False, description="Whether the user completed it.")

    duration_minutes: int | None = Field(
        default=None,
        ge=0,
        description="Actual duration of break taken (if applicable).",
    )
    outcome_window_minutes: int = Field(
        default=30,
        ge=5,
        description="Post-intervention window used to measure outcome.",
    )
    post_state_delta: float | None = Field(
        default=None,
        description="Change in state score after the intervention window.",
    )
    recommended_duration_minutes: int | None = Field(
        default=None,
        ge=0,
        description="Recommended break duration shown to the user.",
    )
    response: InterventionResponse | None = Field(
        default=None,
        description="User response to the recommendation.",
    )
    snoozed_until: datetime | None = Field(default=None, index=True)
    dismissed: bool = Field(default=False)
    break_started_at: datetime | None = Field(default=None)
    actual_break_duration_minutes: int | None = Field(default=None, ge=0)
    feedback_after_break: str | None = Field(default=None, max_length=32)
    model_scores: str | None = Field(
        default=None,
        description="JSON scores used by the recommendation policy.",
    )


class Notification(SQLModel, table=True):
    """User-visible notification stored for the in-app notification center."""

    __tablename__ = "notifications"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(index=True)
    title: str = Field(max_length=160)
    body: str = Field(max_length=1000)
    state: NotificationState = Field(default=NotificationState.UNREAD, index=True)
    intervention_id: int | None = Field(default=None, foreign_key="interventions.id")
    kind: str = Field(default="break_recommendation", max_length=64, index=True)
    action_payload: str | None = Field(default=None, description="JSON action payload.")


class Session(SQLModel, table=True):
    """A derived work session — a contiguous period of activity in one app/task.

    Built by the session builder from raw ActivityEvents.
    """

    __tablename__ = "sessions"

    id: int | None = Field(default=None, primary_key=True)

    ts_start: datetime = Field(index=True)
    ts_end: datetime

    process_name: str = Field(max_length=256)
    task_label: str | None = Field(default=None, max_length=64)

    is_focus: bool = Field(
        default=False,
        description="True if session duration exceeds the focus threshold.",
    )
    is_idle: bool = Field(
        default=False,
        description="True if session is predominantly idle.",
    )

    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Total duration in seconds.",
    )
    context_switches: int = Field(
        default=0,
        ge=0,
        description="Number of app switches within this session.",
    )

    total_keyboard_events: int = Field(default=0, ge=0)
    total_mouse_events: int = Field(default=0, ge=0)
    avg_idle_seconds: float = Field(default=0.0, ge=0.0)


class SchemaVersion(SQLModel, table=True):
    """SQLite schema version marker for safe migrations."""

    __tablename__ = "schema_version"

    id: int | None = Field(default=None, primary_key=True)
    version: int = Field(index=True)
    applied_at: datetime = Field(default_factory=datetime.utcnow)
