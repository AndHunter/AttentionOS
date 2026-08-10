"""Session builder — converts raw ActivityEvents into contiguous work Sessions."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from attentionos.storage.schema import ActivityEvent, Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_FOCUS_THRESHOLD_SEC: float = 120.0  # 2 min — minimum for a "focus block"
DEFAULT_IDLE_RATIO_THRESHOLD: float = 0.5  # > 50% idle → session is idle
DEFAULT_GAP_THRESHOLD_SEC: float = 300.0  # 5 min gap → split into new session


class SessionBuilder:
    """Builds Sessions from raw ActivityEvents.

    Algorithm:
        1. Sort events by ts_start.
        2. Group consecutive events with the same process_name.
        3. If gap between events > gap_threshold → split.
        4. Mark sessions as focus or idle based on thresholds.
        5. Count context switches within each session.
    """

    def __init__(
        self,
        focus_threshold_sec: float = DEFAULT_FOCUS_THRESHOLD_SEC,
        idle_ratio_threshold: float = DEFAULT_IDLE_RATIO_THRESHOLD,
        gap_threshold_sec: float = DEFAULT_GAP_THRESHOLD_SEC,
    ) -> None:
        self._focus_threshold = focus_threshold_sec
        self._idle_ratio = idle_ratio_threshold
        self._gap_threshold = gap_threshold_sec

    def build(self, events: Sequence[ActivityEvent]) -> list[Session]:
        """Convert a sequence of ActivityEvents into Sessions.

        Args:
            events: Raw activity events, ideally pre-sorted by ts_start.

        Returns:
            List of Session objects derived from the events.
        """
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e.ts_start)
        sessions: list[Session] = []
        current_group: list[ActivityEvent] = [sorted_events[0]]

        for i in range(1, len(sorted_events)):
            prev = sorted_events[i - 1]
            curr = sorted_events[i]

            # Check if we should split
            should_split = self._should_split(prev, curr)

            if should_split:
                # Finalize current group
                session = self._group_to_session(current_group)
                if session is not None:
                    sessions.append(session)
                current_group = [curr]
            else:
                current_group.append(curr)

        # Finalize the last group
        if current_group:
            session = self._group_to_session(current_group)
            if session is not None:
                sessions.append(session)

        logger.debug("Built %d sessions from %d events.", len(sessions), len(sorted_events))
        return sessions

    def _should_split(self, prev: ActivityEvent, curr: ActivityEvent) -> bool:
        """Determine if two consecutive events should be in separate sessions."""
        # Different process → new session
        if prev.process_name != curr.process_name:
            return True

        # Large time gap → new session
        gap = (curr.ts_start - prev.ts_end).total_seconds()
        return gap > self._gap_threshold

    def _group_to_session(self, events: list[ActivityEvent]) -> Session | None:
        """Convert a group of events (same process, no gaps) into a Session."""
        if not events:
            return None

        ts_start = events[0].ts_start
        ts_end = events[-1].ts_end
        duration = (ts_end - ts_start).total_seconds()

        # Aggregate metrics
        total_kb = sum(e.keyboard_events for e in events)
        total_mouse = sum(e.mouse_events for e in events)
        total_idle = sum(e.idle_seconds for e in events)
        avg_idle = total_idle / len(events) if events else 0.0

        # Determine idle ratio
        idle_ratio = total_idle / max(duration, 1.0) if duration > 0 else 0.0
        is_idle = idle_ratio > self._idle_ratio

        # Focus = long enough and not idle
        is_focus = duration >= self._focus_threshold and not is_idle

        # Count context switches within group (process changes within the group)
        # Since we split on process_name, switches here are always 0.
        # However, we track sub-process variations (different window titles)
        context_switches = 0
        for i in range(1, len(events)):
            if (
                events[i].window_title_hash != events[i - 1].window_title_hash
                and events[i].window_title_hash
                and events[i - 1].window_title_hash
            ):
                context_switches += 1

        # Determine task label (most common in the group)
        task_label = self._majority_label(events)

        return Session(
            ts_start=ts_start,
            ts_end=ts_end,
            process_name=events[0].process_name,
            task_label=task_label,
            is_focus=is_focus,
            is_idle=is_idle,
            duration_seconds=duration,
            context_switches=context_switches,
            total_keyboard_events=total_kb,
            total_mouse_events=total_mouse,
            avg_idle_seconds=avg_idle,
        )

    @staticmethod
    def _majority_label(events: list[ActivityEvent]) -> str | None:
        """Return the most frequently assigned task label in the group."""
        labels = [e.task_label for e in events if e.task_label]
        if not labels:
            return None
        from collections import Counter

        return Counter(labels).most_common(1)[0][0]


def build_sessions_for_day(
    events: Sequence[ActivityEvent],
    focus_threshold_sec: float = DEFAULT_FOCUS_THRESHOLD_SEC,
    idle_ratio_threshold: float = DEFAULT_IDLE_RATIO_THRESHOLD,
    gap_threshold_sec: float = DEFAULT_GAP_THRESHOLD_SEC,
) -> list[Session]:
    """Convenience function: build sessions from a day's worth of events.

    Args:
        events: Activity events for the day.
        focus_threshold_sec: Minimum duration (s) for a session to be "focus".
        idle_ratio_threshold: Idle ratio above which a session is "idle".
        gap_threshold_sec: Time gap (s) that splits sessions.

    Returns:
        List of derived Sessions.
    """
    builder = SessionBuilder(focus_threshold_sec, idle_ratio_threshold, gap_threshold_sec)
    return builder.build(events)
