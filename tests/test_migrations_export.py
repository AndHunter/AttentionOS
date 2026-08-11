from __future__ import annotations

import sqlite3

from attentionos.storage.db import init_db
from attentionos.storage.export import export_data


def test_migrations_add_schema_version(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    sqlite3.connect(db_path).execute(
        "CREATE TABLE self_reports ("
        "id INTEGER PRIMARY KEY, timestamp DATETIME NOT NULL, "
        "perceived_effectiveness INTEGER NOT NULL, perceived_fatigue INTEGER NOT NULL, "
        "task_difficulty INTEGER, note VARCHAR(500))"
    ).close()

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(self_reports)")}
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert "telemetry_window_start" in columns
    assert "telemetry_window_end" in columns
    assert version >= 2


def test_export_json(tmp_db, sample_events, tmp_path) -> None:
    from attentionos.storage.db import insert_events_batch

    insert_events_batch(sample_events, tmp_db)
    paths = export_data(tmp_path / "export", tmp_db, "json")
    assert paths[0].exists()
    assert paths[0].name == "attentionos_export.json"
