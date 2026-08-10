"""Session metrics — daily summary and context-switch analysis."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from attentionos.storage.schema import Session


@dataclass
class DailySummary:
    """Aggregated metrics for a single day of work."""

    total_active_seconds: float = 0.0
    total_idle_seconds: float = 0.0
    total_sessions: int = 0
    focus_sessions: int = 0
    idle_sessions: int = 0

    mean_focus_block_sec: float = 0.0
    max_focus_block_sec: float = 0.0
    uninterrupted_ratio: float = 0.0

    total_context_switches: int = 0
    unique_apps: int = 0
    switch_entropy: float = 0.0

    total_keyboard_events: int = 0
    total_mouse_events: int = 0

    top_apps: list[tuple[str, float]] = field(default_factory=list)
    task_distribution: dict[str, float] = field(default_factory=dict)

    @property
    def total_active_time(self) -> timedelta:
        return timedelta(seconds=self.total_active_seconds)

    @property
    def total_idle_time(self) -> timedelta:
        return timedelta(seconds=self.total_idle_seconds)

    @property
    def mean_focus_block(self) -> timedelta:
        return timedelta(seconds=self.mean_focus_block_sec)

    @property
    def max_focus_block(self) -> timedelta:
        return timedelta(seconds=self.max_focus_block_sec)


def compute_daily_summary(sessions: Sequence[Session]) -> DailySummary:
    """Compute an aggregate summary from a day's sessions.

    Args:
        sessions: Session objects for a single day.

    Returns:
        DailySummary with all computed metrics.
    """
    if not sessions:
        return DailySummary()

    summary = DailySummary()
    summary.total_sessions = len(sessions)

    focus_durations: list[float] = []
    app_durations: Counter[str] = Counter()
    task_durations: Counter[str] = Counter()

    for s in sessions:
        if s.is_idle:
            summary.idle_sessions += 1
            summary.total_idle_seconds += s.duration_seconds
        else:
            summary.total_active_seconds += s.duration_seconds

        if s.is_focus:
            summary.focus_sessions += 1
            focus_durations.append(s.duration_seconds)

        summary.total_context_switches += s.context_switches
        summary.total_keyboard_events += s.total_keyboard_events
        summary.total_mouse_events += s.total_mouse_events

        app_durations[s.process_name] += s.duration_seconds

        if s.task_label:
            task_durations[s.task_label] += s.duration_seconds

    # Focus metrics
    if focus_durations:
        summary.mean_focus_block_sec = sum(focus_durations) / len(focus_durations)
        summary.max_focus_block_sec = max(focus_durations)
        total_time = summary.total_active_seconds + summary.total_idle_seconds
        if total_time > 0:
            summary.uninterrupted_ratio = sum(focus_durations) / total_time

    # App diversity
    summary.unique_apps = len(app_durations)
    summary.top_apps = app_durations.most_common(10)

    # Switch entropy (Shannon entropy of app transition distribution)
    summary.switch_entropy = _compute_entropy(app_durations)

    # Task distribution (percentage)
    total_task_time = sum(task_durations.values())
    if total_task_time > 0:
        summary.task_distribution = {
            label: duration / total_task_time
            for label, duration in task_durations.most_common()
        }

    return summary


def compute_context_switches(
    sessions: Sequence[Session], window_minutes: int = 15
) -> list[tuple[int, int]]:
    """Compute context switch frequency over rolling time windows.

    Args:
        sessions: Sorted sessions for the day.
        window_minutes: Rolling window size in minutes.

    Returns:
        List of (minute_offset, switch_count) tuples for each window.
    """
    if not sessions:
        return []

    day_start = sessions[0].ts_start
    results: list[tuple[int, int]] = []

    # Compute switches in each window
    window_sec = window_minutes * 60

    # Get all switch timestamps (session boundaries)
    switch_times: list[float] = []
    for i in range(1, len(sessions)):
        if sessions[i].process_name != sessions[i - 1].process_name:
            offset = (sessions[i].ts_start - day_start).total_seconds()
            switch_times.append(offset)

    if not switch_times:
        return [(0, 0)]

    max_offset = int(switch_times[-1]) + window_sec
    for window_start in range(0, max_offset, window_sec):
        window_end = window_start + window_sec
        count = sum(1 for t in switch_times if window_start <= t < window_end)
        results.append((window_start // 60, count))

    return results


def compute_focus_stats(sessions: Sequence[Session]) -> dict[str, float]:
    """Compute focus-related statistics.

    Returns:
        Dictionary with mean_focus_block, max_focus_block, uninterrupted_ratio.
    """
    focus_durations = [s.duration_seconds for s in sessions if s.is_focus]

    if not focus_durations:
        return {
            "mean_focus_block": 0.0,
            "max_focus_block": 0.0,
            "uninterrupted_ratio": 0.0,
        }

    total = sum(s.duration_seconds for s in sessions)

    return {
        "mean_focus_block": sum(focus_durations) / len(focus_durations),
        "max_focus_block": max(focus_durations),
        "uninterrupted_ratio": sum(focus_durations) / max(total, 1.0),
    }


def _compute_entropy(counter: Counter[str]) -> float:
    """Compute Shannon entropy from a Counter."""
    total = sum(counter.values())
    if total == 0:
        return 0.0

    entropy = 0.0
    for count in counter.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy
