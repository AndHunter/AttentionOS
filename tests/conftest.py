"""Pytest fixtures shared across all tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from attentionos.storage.db import init_db, reset_engine
from attentionos.storage.schema import ActivityEvent


@pytest.fixture
def tmp_db(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test.db"
    reset_engine()  # Ensure clean state
    init_db(db_path)
    yield db_path
    reset_engine()  # Cleanup


@pytest.fixture
def sample_events() -> list[ActivityEvent]:
    """Create a list of sample activity events for testing."""
    base_time = datetime(2026, 8, 10, 9, 0, 0, tzinfo=UTC)
    events = []

    # 10 events in code.exe (30 seconds total)
    for i in range(10):
        ts = base_time + timedelta(seconds=i * 3)
        events.append(
            ActivityEvent(
                ts_start=ts,
                ts_end=ts + timedelta(seconds=3),
                process_name="Code.exe",
                idle_seconds=0.5,
                keyboard_events=10 + i,
                mouse_events=3 + i,
                task_label="Coding",
                collector_version="0.1.0-test",
            )
        )

    # 5 events in chrome.exe (15 seconds total) — context switch
    for i in range(5):
        ts = base_time + timedelta(seconds=30 + i * 3)
        events.append(
            ActivityEvent(
                ts_start=ts,
                ts_end=ts + timedelta(seconds=3),
                process_name="chrome.exe",
                idle_seconds=1.0,
                keyboard_events=5,
                mouse_events=8,
                task_label="ML",
                collector_version="0.1.0-test",
            )
        )

    # 3 idle events (9 seconds — above idle threshold for testing)
    for i in range(3):
        ts = base_time + timedelta(seconds=45 + i * 3)
        events.append(
            ActivityEvent(
                ts_start=ts,
                ts_end=ts + timedelta(seconds=3),
                process_name="explorer.exe",
                idle_seconds=200.0,  # Above 120s threshold
                keyboard_events=0,
                mouse_events=0,
                task_label="Rest",
                collector_version="0.1.0-test",
            )
        )

    # 8 more events in Code.exe (24 seconds — second focus block)
    for i in range(8):
        ts = base_time + timedelta(seconds=54 + i * 3)
        events.append(
            ActivityEvent(
                ts_start=ts,
                ts_end=ts + timedelta(seconds=3),
                process_name="Code.exe",
                idle_seconds=0.3,
                keyboard_events=15,
                mouse_events=2,
                task_label="Coding",
                collector_version="0.1.0-test",
            )
        )

    return events


@pytest.fixture
def long_focus_events() -> list[ActivityEvent]:
    """Events that form a single long focus session (> 2 min)."""
    base_time = datetime(2026, 8, 10, 10, 0, 0, tzinfo=UTC)
    events = []

    # 50 events in Code.exe (150 seconds = 2.5 min) — qualifies as focus
    for i in range(50):
        ts = base_time + timedelta(seconds=i * 3)
        events.append(
            ActivityEvent(
                ts_start=ts,
                ts_end=ts + timedelta(seconds=3),
                process_name="Code.exe",
                idle_seconds=0.2,
                keyboard_events=12,
                mouse_events=3,
                task_label="Coding",
                collector_version="0.1.0-test",
            )
        )

    return events
