"""Safe SQLite migrations.

SQLModel can create missing tables, but it does not ALTER existing SQLite
tables. These migrations only add nullable/defaulted columns and never drop
user telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import inspect, text

CURRENT_SCHEMA_VERSION = 2


def run_migrations(engine) -> None:
    """Apply idempotent schema migrations."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "id INTEGER PRIMARY KEY, "
                "version INTEGER NOT NULL, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
    _ensure_self_report_columns(engine)
    _ensure_intervention_columns(engine)
    _set_schema_version(engine, CURRENT_SCHEMA_VERSION)


def _ensure_self_report_columns(engine) -> None:
    columns = _columns(engine, "self_reports")
    additions = {
        "task_name": "VARCHAR(64)",
        "telemetry_window_start": "DATETIME",
        "telemetry_window_end": "DATETIME",
    }
    _add_missing_columns(engine, "self_reports", columns, additions)


def _ensure_intervention_columns(engine) -> None:
    columns = _columns(engine, "interventions")
    additions = {
        "pre_state": "TEXT",
        "post_report_id": "INTEGER",
        "completed": "BOOLEAN NOT NULL DEFAULT 0",
    }
    _add_missing_columns(engine, "interventions", columns, additions)


def _columns(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _add_missing_columns(
    engine, table: str, existing: set[str], additions: dict[str, str]
) -> None:
    if not existing:
        return
    with engine.begin() as conn:
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def _set_schema_version(engine, version: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM schema_version"))
        conn.execute(
            text(
                "INSERT INTO schema_version (version, applied_at) "
                "VALUES (:version, :applied_at)"
            ),
            {"version": version, "applied_at": datetime.now(tz=UTC)},
        )
