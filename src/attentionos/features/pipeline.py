"""Feature pipeline — computes rolling window features from ActivityEvents."""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from attentionos.sessions.builder import SessionBuilder
from attentionos.storage.schema import ActivityEvent, Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task label encoding
# ---------------------------------------------------------------------------

DEFAULT_LABEL_MAP: dict[str, int] = {
    "Coding": 1,
    "ML": 2,
    "Math": 3,
    "English": 4,
    "Rest": 5,
    "Meeting": 6,
    "Admin": 7,
    "Other": 8,
}


class FeaturePipeline:
    """Computes engineered features from raw events.

    All features are computed causally: only past data is used.
    Rolling windows: 15, 30, 60, 120 minutes.
    """

    def __init__(
        self,
        label_map: dict[str, int] | None = None,
        break_threshold_min: float = 5.0,
    ) -> None:
        self._label_map = label_map or DEFAULT_LABEL_MAP
        self._break_threshold_sec = break_threshold_min * 60.0
        self._session_builder = SessionBuilder()

    def compute_features_at(
        self,
        events: Sequence[ActivityEvent],
        at_time: datetime,
    ) -> dict[str, float | int]:
        """Compute all features at a specific point in time.

        Only uses events with ts_end <= at_time (strictly causal).

        Args:
            events: All available events (will be filtered).
            at_time: The point in time to compute features for.

        Returns:
            Dictionary mapping feature name → value.
        """
        # Filter to causal events only
        causal = [e for e in events if e.ts_end <= at_time]
        if not causal:
            return self._empty_features(at_time)

        causal_sorted = sorted(causal, key=lambda e: e.ts_start)

        # Build sessions from causal events
        sessions = self._session_builder.build(causal_sorted)

        features: dict[str, float | int] = {}

        # --- Focus features ---
        focus_sessions = [s for s in sessions if s.is_focus]
        if focus_sessions:
            durations = [s.duration_seconds for s in focus_sessions]
            features["mean_focus_block_sec"] = float(sum(durations) / len(durations))
            features["max_focus_block_sec"] = float(max(durations))
            total_time = sum(s.duration_seconds for s in sessions)
            features["uninterrupted_ratio"] = sum(durations) / max(total_time, 1.0)
        else:
            features["mean_focus_block_sec"] = 0.0
            features["max_focus_block_sec"] = 0.0
            features["uninterrupted_ratio"] = 0.0

        # --- Switching features (windowed) ---
        for window_min in [15, 30, 60]:
            cutoff = at_time - timedelta(minutes=window_min)
            window_events = [e for e in causal_sorted if e.ts_start >= cutoff]
            switches = self._count_switches(window_events)
            features[f"switches_{window_min}m"] = switches

        unique_apps = len(set(e.process_name for e in causal_sorted))
        features["unique_apps"] = unique_apps
        features["switch_entropy"] = self._app_entropy(causal_sorted)

        # --- Idle features ---
        total_time = sum(
            (e.ts_end - e.ts_start).total_seconds() for e in causal_sorted
        )
        total_idle = sum(e.idle_seconds for e in causal_sorted)
        features["idle_ratio"] = total_idle / max(total_time, 1.0)
        features["idle_bursts"] = self._count_idle_bursts(causal_sorted)
        features["time_since_last_break_min"] = self._time_since_last_break(
            sessions, at_time
        )

        # --- Input dynamics ---
        window_60 = [
            e
            for e in causal_sorted
            if e.ts_start >= at_time - timedelta(minutes=60)
        ]
        if window_60:
            duration_min = max(
                (window_60[-1].ts_end - window_60[0].ts_start).total_seconds() / 60.0,
                1.0 / 60.0,
            )
            total_kb = sum(e.keyboard_events for e in window_60)
            total_mouse = sum(e.mouse_events for e in window_60)
            features["keyboard_rate"] = total_kb / duration_min
            features["mouse_rate"] = total_mouse / duration_min

            # Rate change vs overall average
            overall_kb = sum(e.keyboard_events for e in causal_sorted)
            overall_mouse = sum(e.mouse_events for e in causal_sorted)
            overall_dur = max(
                (causal_sorted[-1].ts_end - causal_sorted[0].ts_start).total_seconds()
                / 60.0,
                1.0 / 60.0,
            )
            avg_kb_rate = overall_kb / overall_dur
            avg_mouse_rate = overall_mouse / overall_dur

            features["kb_rate_change_pct"] = (
                ((features["keyboard_rate"] - avg_kb_rate) / max(avg_kb_rate, 0.01))
                * 100
            )
            features["mouse_rate_change_pct"] = (
                ((features["mouse_rate"] - avg_mouse_rate) / max(avg_mouse_rate, 0.01))
                * 100
            )
        else:
            features["keyboard_rate"] = 0.0
            features["mouse_rate"] = 0.0
            features["kb_rate_change_pct"] = 0.0
            features["mouse_rate_change_pct"] = 0.0

        # --- Temporal features ---
        features["hour_of_day"] = at_time.hour
        hour_fraction = at_time.hour + at_time.minute / 60.0
        features["hour_sin"] = math.sin(2 * math.pi * hour_fraction / 24.0)
        features["hour_cos"] = math.cos(2 * math.pi * hour_fraction / 24.0)
        features["weekday"] = at_time.weekday()

        # Session age: time since current continuous work block started
        if sessions:
            last_session = sessions[-1]
            features["session_age_min"] = (
                at_time - last_session.ts_start
            ).total_seconds() / 60.0
        else:
            features["session_age_min"] = 0.0

        # Work since day start
        if causal_sorted:
            day_start = causal_sorted[0].ts_start
            features["work_since_day_start_min"] = (
                at_time - day_start
            ).total_seconds() / 60.0
        else:
            features["work_since_day_start_min"] = 0.0

        # --- Workload features ---
        window_2h = [
            e for e in causal_sorted if e.ts_start >= at_time - timedelta(hours=2)
        ]
        active_2h = sum(
            (e.ts_end - e.ts_start).total_seconds() / 60.0
            for e in window_2h
            if e.idle_seconds < 120
        )
        features["active_minutes_2h"] = active_2h

        active_day = sum(
            (e.ts_end - e.ts_start).total_seconds() / 60.0
            for e in causal_sorted
            if e.idle_seconds < 120
        )
        features["active_minutes_day"] = active_day

        # Previous session length
        if len(sessions) >= 2:
            features["previous_session_length_min"] = (
                sessions[-2].duration_seconds / 60.0
            )
        else:
            features["previous_session_length_min"] = 0.0

        # --- Task ---
        current_label = causal_sorted[-1].task_label if causal_sorted else None
        features["task_label_encoded"] = self._label_map.get(
            current_label or "", 0
        )

        return features

    def compute_features_series(
        self,
        events: Sequence[ActivityEvent],
        interval_minutes: int = 30,
    ) -> pd.DataFrame:
        """Compute features at regular intervals throughout the day.

        Args:
            events: All events for the day.
            interval_minutes: Interval between feature computations.

        Returns:
            DataFrame with timestamp index and feature columns.
        """
        import pandas as pd

        if not events:
            return pd.DataFrame()

        sorted_events = sorted(events, key=lambda e: e.ts_start)
        start = sorted_events[0].ts_start
        end = sorted_events[-1].ts_end

        rows: list[dict] = []
        current = start + timedelta(minutes=interval_minutes)

        while current <= end:
            features = self.compute_features_at(events, current)
            features["timestamp"] = current
            rows.append(features)
            current += timedelta(minutes=interval_minutes)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _count_switches(events: list[ActivityEvent]) -> int:
        """Count process name changes in a sequence of events."""
        if len(events) < 2:
            return 0
        return sum(
            1
            for i in range(1, len(events))
            if events[i].process_name != events[i - 1].process_name
        )

    @staticmethod
    def _app_entropy(events: list[ActivityEvent]) -> float:
        """Compute Shannon entropy of app usage distribution."""
        counter = Counter(e.process_name for e in events)
        total = sum(counter.values())
        if total == 0:
            return 0.0
        entropy = 0.0
        for count in counter.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        return entropy

    @staticmethod
    def _count_idle_bursts(events: list[ActivityEvent]) -> int:
        """Count transitions from active to idle in events."""
        if len(events) < 2:
            return 0
        threshold = 120.0  # Same as idle threshold
        bursts = 0
        for i in range(1, len(events)):
            if events[i].idle_seconds >= threshold and events[i - 1].idle_seconds < threshold:
                bursts += 1
        return bursts

    def _time_since_last_break(
        self, sessions: Sequence[Session], at_time: datetime
    ) -> float:
        """Minutes since the last idle session >= break threshold."""
        for s in reversed(sessions):
            if s.is_idle and s.duration_seconds >= self._break_threshold_sec:
                return (at_time - s.ts_end).total_seconds() / 60.0
        # No break found — return time since first session
        if sessions:
            return (at_time - sessions[0].ts_start).total_seconds() / 60.0
        return 0.0

    def _empty_features(self, at_time: datetime) -> dict[str, float | int]:
        """Return a feature vector with all zeros for the given time."""
        return {
            "mean_focus_block_sec": 0.0,
            "max_focus_block_sec": 0.0,
            "uninterrupted_ratio": 0.0,
            "switches_15m": 0,
            "switches_30m": 0,
            "switches_60m": 0,
            "unique_apps": 0,
            "switch_entropy": 0.0,
            "idle_ratio": 0.0,
            "idle_bursts": 0,
            "time_since_last_break_min": 0.0,
            "keyboard_rate": 0.0,
            "mouse_rate": 0.0,
            "kb_rate_change_pct": 0.0,
            "mouse_rate_change_pct": 0.0,
            "hour_of_day": at_time.hour,
            "hour_sin": math.sin(2 * math.pi * (at_time.hour + at_time.minute / 60.0) / 24.0),
            "hour_cos": math.cos(2 * math.pi * (at_time.hour + at_time.minute / 60.0) / 24.0),
            "weekday": at_time.weekday(),
            "session_age_min": 0.0,
            "work_since_day_start_min": 0.0,
            "active_minutes_2h": 0.0,
            "active_minutes_day": 0.0,
            "previous_session_length_min": 0.0,
            "task_label_encoded": 0,
        }
