"""Tests for the storage layer (schema + database operations)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from attentionos.storage.db import (
    get_daily_events,
    get_events_range,
    insert_event,
    insert_events_batch,
    insert_self_report,
)
from attentionos.storage.schema import ActivityEvent, SelfReport


class TestActivityEventCRUD:
    """Test ActivityEvent insert and query operations."""

    def test_insert_single_event(self, tmp_db):
        event = ActivityEvent(
            ts_start=datetime(2026, 8, 10, 9, 0, 0, tzinfo=UTC),
            ts_end=datetime(2026, 8, 10, 9, 0, 3, tzinfo=UTC),
            process_name="Code.exe",
            idle_seconds=0.5,
            keyboard_events=10,
            mouse_events=3,
            collector_version="0.1.0-test",
        )
        result = insert_event(event, tmp_db)
        assert result.id is not None
        assert result.process_name == "Code.exe"

    def test_insert_batch(self, tmp_db, sample_events):
        count = insert_events_batch(sample_events, tmp_db)
        assert count == len(sample_events)

    def test_insert_empty_batch(self, tmp_db):
        count = insert_events_batch([], tmp_db)
        assert count == 0

    def test_query_events_range(self, tmp_db, sample_events):
        insert_events_batch(sample_events, tmp_db)

        start = datetime(2026, 8, 10, 8, 0, 0, tzinfo=UTC)
        end = datetime(2026, 8, 10, 10, 0, 0, tzinfo=UTC)
        results = get_events_range(start, end, tmp_db)

        assert len(results) == len(sample_events)

    def test_query_events_partial_range(self, tmp_db, sample_events):
        insert_events_batch(sample_events, tmp_db)

        # Query only the first 30 seconds (first 10 events: Code.exe)
        start = datetime(2026, 8, 10, 9, 0, 0, tzinfo=UTC)
        end = datetime(2026, 8, 10, 9, 0, 30, tzinfo=UTC)
        results = get_events_range(start, end, tmp_db)

        assert len(results) == 10
        assert all(r.process_name == "Code.exe" for r in results)

    def test_query_daily_events(self, tmp_db, sample_events):
        insert_events_batch(sample_events, tmp_db)

        from datetime import date
        results = get_daily_events(date(2026, 8, 10), tmp_db)
        assert len(results) == len(sample_events)

    def test_event_fields_preserved(self, tmp_db):
        event = ActivityEvent(
            ts_start=datetime(2026, 8, 10, 14, 30, 0, tzinfo=UTC),
            ts_end=datetime(2026, 8, 10, 14, 30, 3, tzinfo=UTC),
            process_name="python.exe",
            window_title_hash="abc123",
            idle_seconds=5.5,
            keyboard_events=42,
            mouse_events=7,
            task_label="ML",
            collector_version="0.1.0",
        )
        insert_event(event, tmp_db)

        results = get_daily_events(datetime(2026, 8, 10).date(), tmp_db)
        assert len(results) == 1
        r = results[0]
        assert r.process_name == "python.exe"
        assert r.window_title_hash == "abc123"
        assert r.keyboard_events == 42
        assert r.task_label == "ML"


class TestSelfReportCRUD:
    """Test SelfReport insert and query."""

    def test_insert_self_report(self, tmp_db):
        report = SelfReport(
            timestamp=datetime(2026, 8, 10, 11, 0, 0, tzinfo=UTC),
            perceived_effectiveness=4,
            perceived_fatigue=2,
            task_difficulty=3,
            note="Feeling focused",
        )
        result = insert_self_report(report, tmp_db)
        assert result.id is not None
        assert result.perceived_effectiveness == 4

    def test_self_report_validation(self):
        """Effectiveness and fatigue must be 1-5."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SelfReport.model_validate(
                {
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                    "perceived_effectiveness": 6,  # Out of range
                    "perceived_fatigue": 2,
                }
            )
