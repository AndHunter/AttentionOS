"""Small presentation helpers for the native dashboard."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from attentionos.sessions.builder import build_sessions_for_day
from attentionos.sessions.metrics import (
    DailySummary,
    compute_context_switches,
    compute_daily_summary,
)
from attentionos.storage.schema import ActivityEvent, Session


@dataclass(frozen=True)
class DashboardSnapshot:
    """Prepared daily data for the desktop UI."""

    target_date: date
    event_count: int
    sessions: list[Session]
    summary: DailySummary
    switch_windows: list[tuple[int, int]]

    @property
    def is_today(self) -> bool:
        return self.target_date == date.today()


@dataclass(frozen=True)
class TopApp:
    """Ranked app usage entry."""

    name: str
    seconds: float
    percent: float


@dataclass(frozen=True)
class CurrentState:
    """User-facing state summary derived from existing metrics."""

    value: str
    label: str
    detail: str


def build_dashboard_snapshot(
    events: Sequence[ActivityEvent],
    target_date: date,
) -> DashboardSnapshot:
    """Build sessions and summary metrics from raw events."""
    sessions = build_sessions_for_day(events)
    summary = compute_daily_summary(sessions)
    switch_windows = compute_context_switches(sessions, window_minutes=15)
    return DashboardSnapshot(
        target_date=target_date,
        event_count=len(events),
        sessions=sessions,
        summary=summary,
        switch_windows=switch_windows,
    )


def format_duration(seconds: float) -> str:
    """Format a duration for compact dashboard metrics."""
    if seconds <= 0:
        return "0m"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes}m"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours}h"
    return f"{hours}h {rest}m"


def clean_app_name(process_name: str) -> str:
    """Return a readable app name from a process executable."""
    name = process_name.strip() or "Unknown"
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name


def compute_current_state(summary: DailySummary) -> CurrentState:
    """Derive a conservative current-state display from existing data only."""
    if summary.total_sessions == 0:
        return CurrentState("—", "No data yet", "Start tracking to build today's baseline.")
    if summary.focus_sessions > 0:
        minutes = int(round(summary.max_focus_block_sec / 60))
        return CurrentState(
            str(minutes),
            "Best focus block",
            "Minutes, longest focus block.",
        )
    if summary.total_active_seconds > 0:
        return CurrentState(
            format_duration(summary.total_active_seconds),
            "Active",
            "No focus block yet.",
        )
    return CurrentState("Idle", "Quiet day", "No active sessions recorded yet.")


def build_top_apps(summary: DailySummary, limit: int = 5) -> list[TopApp]:
    """Return ranked app entries with percentages."""
    total = sum(seconds for _name, seconds in summary.top_apps)
    if total <= 0:
        return []
    return [
        TopApp(clean_app_name(name), seconds, seconds / total * 100)
        for name, seconds in summary.top_apps[:limit]
    ]
