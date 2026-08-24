"""Feature engineering from telemetry windows.

Features are causal: each self-report uses only telemetry before the report.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta

from attentionos.sessions.builder import SessionBuilder
from attentionos.storage.schema import ActivityEvent

FEATURE_WINDOW_MINUTES = 30
FEATURE_SCHEMA_VERSION = "v1"
FOCUS_THRESHOLD_SECONDS = 25 * 60
IDLE_THRESHOLD_SECONDS = 5 * 60


def compute_feature_window(
    events: Sequence[ActivityEvent],
    window_start: datetime,
    window_end: datetime,
    all_day_events: Sequence[ActivityEvent] | None = None,
) -> dict[str, float | int]:
    """Compute a compact ML feature vector for one report window."""
    window = sorted(
        [event for event in events if window_start <= event.ts_start <= window_end],
        key=lambda event: event.ts_start,
    )
    day_events = sorted(all_day_events or events, key=lambda event: event.ts_start)
    if not window:
        return _empty_features(window_end)

    duration = max((window[-1].ts_end - window[0].ts_start).total_seconds(), 1.0)
    active_events = [event for event in window if event.idle_seconds < IDLE_THRESHOLD_SECONDS]
    active_time = sum(_event_duration(event) for event in active_events)
    idle_time = max(duration - active_time, 0.0)
    switches = _count_switches(window)
    input_events = sum(event.keyboard_events + event.mouse_events for event in window)

    sessions = SessionBuilder(focus_threshold_sec=FOCUS_THRESHOLD_SECONDS).build(window)
    breaks = [session for session in sessions if session.is_idle]
    time_since_last_break = (
        (window_end - breaks[-1].ts_end).total_seconds() / 60.0 if breaks else duration / 60.0
    )

    today_active = sum(
        _event_duration(event)
        for event in day_events
        if event.ts_start.date() == window_end.date()
        and event.ts_start <= window_end
        and event.idle_seconds < IDLE_THRESHOLD_SECONDS
    )
    today_focus = _focused_time(day_events, window_end)
    hour = window_end.hour + window_end.minute / 60.0

    return {
        "session_duration": duration,
        "active_time": active_time,
        "idle_time": idle_time,
        "idle_ratio": idle_time / duration,
        "context_switch_count": switches,
        "context_switch_rate": switches / max(duration / 60.0, 1e-6),
        "keyboard_event_count": sum(event.keyboard_events for event in window),
        "mouse_event_count": sum(event.mouse_events for event in window),
        "input_event_rate": input_events / max(duration / 60.0, 1e-6),
        "unique_apps": len({event.process_name for event in window}),
        "time_of_day_sin": math.sin(2 * math.pi * hour / 24),
        "time_of_day_cos": math.cos(2 * math.pi * hour / 24),
        "total_active_time_today": today_active,
        "focused_time_today": today_focus,
        "time_since_last_break": time_since_last_break,
        "app_entropy": _app_entropy(window),
        "current_task_duration": _current_task_duration(window),
        "switches_last_5m": _count_switches_since(window, window_end - timedelta(minutes=5)),
        "switches_last_15m": _count_switches_since(window, window_end - timedelta(minutes=15)),
    }


def _empty_features(at_time: datetime) -> dict[str, float | int]:
    hour = at_time.hour + at_time.minute / 60.0
    return {
        "session_duration": 0.0,
        "active_time": 0.0,
        "idle_time": 0.0,
        "idle_ratio": 0.0,
        "context_switch_count": 0,
        "context_switch_rate": 0.0,
        "keyboard_event_count": 0,
        "mouse_event_count": 0,
        "input_event_rate": 0.0,
        "unique_apps": 0,
        "time_of_day_sin": math.sin(2 * math.pi * hour / 24),
        "time_of_day_cos": math.cos(2 * math.pi * hour / 24),
        "total_active_time_today": 0.0,
        "focused_time_today": 0.0,
        "time_since_last_break": 0.0,
        "app_entropy": 0.0,
        "current_task_duration": 0.0,
        "switches_last_5m": 0,
        "switches_last_15m": 0,
    }


def _event_duration(event: ActivityEvent) -> float:
    return max((event.ts_end - event.ts_start).total_seconds(), 0.0)


def _count_switches(events: Sequence[ActivityEvent]) -> int:
    return sum(
        1
        for index in range(1, len(events))
        if events[index].process_name != events[index - 1].process_name
    )


def _count_switches_since(events: Sequence[ActivityEvent], cutoff: datetime) -> int:
    return _count_switches([event for event in events if event.ts_start >= cutoff])


def _app_entropy(events: Sequence[ActivityEvent]) -> float:
    durations: Counter[str] = Counter()
    for event in events:
        durations[event.process_name] += _event_duration(event)
    total = sum(durations.values())
    if total <= 0:
        return 0.0
    return -sum((value / total) * math.log(value / total) for value in durations.values())


def _focused_time(events: Sequence[ActivityEvent], at_time: datetime) -> float:
    today = [
        event
        for event in events
        if event.ts_start.date() == at_time.date() and event.ts_start <= at_time
    ]
    sessions = SessionBuilder(focus_threshold_sec=FOCUS_THRESHOLD_SECONDS).build(today)
    return sum(session.duration_seconds for session in sessions if session.is_focus)


def _current_task_duration(events: Sequence[ActivityEvent]) -> float:
    if not events:
        return 0.0
    task = events[-1].task_label
    total = 0.0
    for event in reversed(events):
        if event.task_label != task:
            break
        total += _event_duration(event)
    return total
