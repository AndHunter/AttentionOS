from __future__ import annotations

from datetime import UTC, datetime

from attentionos.collector.engine import CollectorEngine
from attentionos.settings import RuntimeSettings
from attentionos.storage.schema import ActivityEvent


def test_excluded_applications_are_ignored() -> None:
    settings = RuntimeSettings()
    settings.tracking.excluded_applications = ["KeePass.exe"]
    engine = CollectorEngine(runtime_settings=settings)
    event = ActivityEvent(
        ts_start=datetime.now(tz=UTC),
        ts_end=datetime.now(tz=UTC),
        process_name="KeePass.exe",
    )
    assert engine._should_ignore(event)
