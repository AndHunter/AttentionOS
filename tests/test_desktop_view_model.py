"""Tests for native desktop presentation helpers."""

from __future__ import annotations

from datetime import date

from attentionos.desktop.view_model import (
    build_dashboard_snapshot,
    build_top_apps,
    clean_app_name,
    compute_current_state,
    format_duration,
)
from attentionos.sessions.metrics import DailySummary


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


def test_current_state_empty_is_not_fake_score() -> None:
    state = compute_current_state(DailySummary())
    assert state.value == "—"
    assert state.label == "No data yet"


def test_top_apps_percentages() -> None:
    summary = DailySummary(top_apps=[("Code.exe", 90), ("chrome.exe", 10)])
    apps = build_top_apps(summary)
    assert apps[0].name == "Code"
    assert apps[0].percent == 90
    assert apps[1].name == "chrome"
