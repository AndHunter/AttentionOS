"""Tests for native desktop presentation helpers."""

from __future__ import annotations

from datetime import date

from attentionos.desktop.view_model import (
    build_dashboard_snapshot,
    clean_app_name,
    format_duration,
)


def test_format_duration_compact() -> None:
    assert format_duration(0) == "0m"
    assert format_duration(61) == "1m"
    assert format_duration(3600) == "1h"
    assert format_duration(5400) == "1h 30m"


def test_clean_app_name() -> None:
    assert clean_app_name("Code.exe") == "Code"
    assert clean_app_name("") == "Unknown"


def test_dashboard_snapshot_uses_existing_metrics(sample_events) -> None:
    snapshot = build_dashboard_snapshot(sample_events, date(2026, 8, 10))
    assert snapshot.event_count == len(sample_events)
    assert snapshot.summary.unique_apps >= 2
    assert snapshot.sessions
