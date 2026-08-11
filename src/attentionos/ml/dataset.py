"""Build supervised datasets from self-reports and preceding telemetry."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import pandas as pd

from attentionos.ml.baseline import PersonalBaselineProfile
from attentionos.ml.features import FEATURE_WINDOW_MINUTES, compute_feature_window
from attentionos.storage.schema import ActivityEvent, SelfReport


def build_effectiveness_dataset(
    events: Sequence[ActivityEvent],
    reports: Sequence[SelfReport],
    feature_window_minutes: int = FEATURE_WINDOW_MINUTES,
) -> pd.DataFrame:
    """Return rows ordered by report timestamp with y=effectiveness."""
    sorted_events = sorted(events, key=lambda event: event.ts_start)
    sorted_reports = sorted(reports, key=lambda report: report.timestamp)
    baseline = PersonalBaselineProfile()
    rows: list[dict[str, object]] = []

    for report in sorted_reports:
        window_end = report.telemetry_window_end or report.timestamp
        window_start = report.telemetry_window_start or (
            window_end - timedelta(minutes=feature_window_minutes)
        )
        features = compute_feature_window(sorted_events, window_start, window_end, sorted_events)
        relative = baseline.relative_features(features)
        baseline.update(features)
        rows.append(
            {
                "report_id": report.id,
                "timestamp": report.timestamp,
                "task_name": report.task_name,
                "window_start": window_start,
                "window_end": window_end,
                **features,
                **relative,
                "effectiveness": report.perceived_effectiveness,
                "fatigue": report.perceived_fatigue,
                "difficulty": report.task_difficulty,
            }
        )

    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def chronological_split(
    dataset: pd.DataFrame, validation_ratio: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rows chronologically without shuffling."""
    if dataset.empty:
        return dataset.copy(), dataset.copy()
    ordered = dataset.sort_values("timestamp").reset_index(drop=True)
    split_at = max(int(len(ordered) * (1 - validation_ratio)), 1)
    if split_at >= len(ordered):
        split_at = len(ordered) - 1
    return ordered.iloc[:split_at].copy(), ordered.iloc[split_at:].copy()
