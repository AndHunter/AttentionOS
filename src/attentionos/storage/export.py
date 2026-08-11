"""Structured local data export for analysis and ML preparation."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Literal

from sqlmodel import select

from attentionos.storage.db import get_session
from attentionos.storage.schema import ActivityEvent, SelfReport

ExportFormat = Literal["json", "csv"]


def export_data(
    output_dir: Path | str,
    db_path: Path | str | None = None,
    export_format: ExportFormat = "json",
) -> list[Path]:
    """Export telemetry and labels without synthetic predictions."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with get_session(db_path) as session:
        events = [event.model_dump(mode="json") for event in session.exec(select(ActivityEvent))]
        reports = [report.model_dump(mode="json") for report in session.exec(select(SelfReport))]

    if export_format == "json":
        path = output / "attentionos_export.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump({"activity_events": events, "self_reports": reports}, handle, indent=2)
        return [path]

    event_path = output / "activity_events.csv"
    report_path = output / "self_reports.csv"
    _write_csv(event_path, events)
    _write_csv(report_path, reports)
    return [event_path, report_path]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
