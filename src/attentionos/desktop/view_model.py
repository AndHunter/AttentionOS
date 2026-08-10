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
