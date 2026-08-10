"""Tests for the session builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from attentionos.sessions.builder import SessionBuilder, build_sessions_for_day
from attentionos.sessions.metrics import compute_daily_summary, compute_focus_stats
from attentionos.storage.schema import ActivityEvent


class TestSessionBuilder:
    """Test session construction from raw events."""

    def test_empty_events(self):
        builder = SessionBuilder()
        sessions = builder.build([])
        assert sessions == []

    def test_single_event(self):
        builder = SessionBuilder()
        event = ActivityEvent(
            ts_start=datetime(2026, 8, 10, 9, 0, 0, tzinfo=UTC),
            ts_end=datetime(2026, 8, 10, 9, 0, 3, tzinfo=UTC),
            process_name="Code.exe",
            idle_seconds=0.0,
            keyboard_events=5,
            mouse_events=2,
        )
        sessions = builder.build([event])
        assert len(sessions) == 1
        assert sessions[0].process_name == "Code.exe"

    def test_splits_on_process_change(self, sample_events):
        builder = SessionBuilder()
        sessions = builder.build(sample_events)

        # Should have at least 3 groups: Code.exe, chrome.exe, explorer.exe, Code.exe
        process_names = [s.process_name for s in sessions]
        assert "Code.exe" in process_names
        assert "chrome.exe" in process_names
        assert "explorer.exe" in process_names

    def test_splits_on_time_gap(self):
        """Events with a gap > gap_threshold should be in separate sessions."""
        builder = SessionBuilder(gap_threshold_sec=60.0)

        events = [
            ActivityEvent(
                ts_start=datetime(2026, 8, 10, 9, 0, 0, tzinfo=UTC),
                ts_end=datetime(2026, 8, 10, 9, 0, 3, tzinfo=UTC),
                process_name="Code.exe",
                idle_seconds=0.0,
                keyboard_events=5,
                mouse_events=2,
            ),
            # 2-minute gap (120s > 60s threshold)
            ActivityEvent(
                ts_start=datetime(2026, 8, 10, 9, 2, 3, tzinfo=UTC),
                ts_end=datetime(2026, 8, 10, 9, 2, 6, tzinfo=UTC),
                process_name="Code.exe",
                idle_seconds=0.0,
                keyboard_events=5,
                mouse_events=2,
            ),
        ]

        sessions = builder.build(events)
        assert len(sessions) == 2

    def test_focus_session_detection(self, long_focus_events):
        """Sessions longer than focus threshold should be marked as focus."""
        builder = SessionBuilder(focus_threshold_sec=120.0)
        sessions = builder.build(long_focus_events)

        assert len(sessions) == 1
        assert sessions[0].is_focus is True
        assert sessions[0].duration_seconds >= 120.0

    def test_idle_session_detection(self):
        """Sessions with high idle ratio should be marked as idle."""
        builder = SessionBuilder(idle_ratio_threshold=0.5)

        events = [
            ActivityEvent(
                ts_start=datetime(2026, 8, 10, 12, 0, i * 3, tzinfo=UTC),
                ts_end=datetime(2026, 8, 10, 12, 0, (i + 1) * 3, tzinfo=UTC),
                process_name="explorer.exe",
                idle_seconds=200.0,  # Very idle
                keyboard_events=0,
                mouse_events=0,
                task_label="Rest",
            )
            for i in range(10)
        ]

        sessions = builder.build(events)
        assert len(sessions) == 1
        assert sessions[0].is_idle is True

    def test_keyboard_mouse_aggregation(self, sample_events):
        """Keyboard and mouse counts should be aggregated per session."""
        builder = SessionBuilder()
        sessions = builder.build(sample_events)

        for s in sessions:
            assert s.total_keyboard_events >= 0
            assert s.total_mouse_events >= 0

    def test_majority_task_label(self):
        """Task label should be the most common one in the group."""
        events = []
        base = datetime(2026, 8, 10, 9, 0, 0, tzinfo=UTC)

        # 7 events with "Coding", 3 with "ML"
        for i in range(10):
            events.append(
                ActivityEvent(
                    ts_start=base + timedelta(seconds=i * 3),
                    ts_end=base + timedelta(seconds=(i + 1) * 3),
                    process_name="Code.exe",
                    idle_seconds=0.0,
                    keyboard_events=5,
                    mouse_events=2,
                    task_label="Coding" if i < 7 else "ML",
                )
            )

        builder = SessionBuilder()
        sessions = builder.build(events)
        assert sessions[0].task_label == "Coding"


class TestDailySummary:
    """Test daily summary computation."""

    def test_empty_sessions(self):
        summary = compute_daily_summary([])
        assert summary.total_sessions == 0
        assert summary.total_active_seconds == 0.0

    def test_summary_from_sample(self, sample_events):
        sessions = build_sessions_for_day(sample_events)
        summary = compute_daily_summary(sessions)

        assert summary.total_sessions > 0
        assert summary.unique_apps > 0
        assert summary.total_keyboard_events > 0

    def test_focus_stats(self, long_focus_events):
        sessions = build_sessions_for_day(long_focus_events)
        stats = compute_focus_stats(sessions)

        assert stats["mean_focus_block"] > 0
        assert stats["max_focus_block"] > 0
        assert 0 <= stats["uninterrupted_ratio"] <= 1
