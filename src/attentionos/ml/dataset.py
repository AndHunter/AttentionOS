"""Build supervised datasets from self-reports and preceding telemetry."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

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


def build_action_outcome_dataset(
    recommendations: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    *,
    include_invalid: bool = False,
) -> pd.DataFrame:
    """Build real action-outcome rows: X_t + action_t -> Y_future.

    This function intentionally accepts only real recommendation/outcome rows.
    Synthetic demo rows should be built by the demo simulator pipeline instead.
    """
    recommendation_by_id = {
        int(row["id"]): row
        for row in recommendations
        if row.get("id") is not None
    }
    rows: list[dict[str, object]] = []
    for outcome in outcomes:
        outcome_quality = str(outcome.get("outcome_quality") or "VALID")
        if not include_invalid and outcome_quality != "VALID":
            continue
        recommendation_id = outcome.get("recommendation_id")
        if recommendation_id is None:
            continue
        recommendation = recommendation_by_id.get(int(recommendation_id))
        if recommendation is None:
            continue
        effectiveness_before = _optional_float(recommendation.get("effectiveness_before"))
        effectiveness_after = _optional_float(outcome.get("effectiveness_after"))
        rows.append(
            {
                "recommendation_id": int(recommendation_id),
                "created_at": recommendation.get("created_at") or recommendation.get("timestamp"),
                "captured_at": outcome.get("captured_at"),
                "model_version": recommendation.get("model_version"),
                "policy_source": recommendation.get("policy_source"),
                "task_id": recommendation.get("task_id") or recommendation.get("task_before"),
                "task_category": recommendation.get("task_category"),
                "action": outcome.get("action") or recommendation.get("recommended_action"),
                "recommended_break_minutes": _optional_float(
                    recommendation.get("recommended_break_minutes")
                    or recommendation.get("recommended_duration")
                ),
                "actual_break_seconds": _optional_float(
                    recommendation.get("actual_break_seconds")
                ),
                "accepted": bool(recommendation.get("accepted") or False),
                "ignored": bool(recommendation.get("ignored") or False),
                "effectiveness_before": effectiveness_before,
                "decline_15_before": _optional_float(recommendation.get("decline_15")),
                "decline_30_before": _optional_float(recommendation.get("decline_30")),
                "decline_60_before": _optional_float(recommendation.get("decline_60")),
                "break_benefit_before": _optional_float(recommendation.get("break_benefit")),
                "minutes_since_action": int(outcome.get("minutes_since_action") or 0),
                "effectiveness_after": effectiveness_after,
                "decline_15_after": _optional_float(outcome.get("decline_15_after")),
                "decline_30_after": _optional_float(outcome.get("decline_30_after")),
                "decline_60_after": _optional_float(outcome.get("decline_60_after")),
                "active_ratio_after": _optional_float(outcome.get("active_ratio_after")),
                "switch_rate_after": _optional_float(outcome.get("switch_rate_after")),
                "input_rate_after": _optional_float(outcome.get("input_rate_after")),
                "idle_ratio_after": _optional_float(outcome.get("idle_ratio_after")),
                "task_after": outcome.get("task_after"),
                "outcome_quality": outcome_quality,
                "quality_reason": outcome.get("quality_reason"),
                "future_effectiveness_delta": (
                    effectiveness_after - effectiveness_before
                    if effectiveness_before is not None and effectiveness_after is not None
                    else None
                ),
            }
        )
    dataset = pd.DataFrame(rows)
    if dataset.empty:
        return dataset
    return dataset.sort_values(["created_at", "minutes_since_action"]).reset_index(drop=True)


def load_real_action_outcome_dataset(db_path: Path) -> pd.DataFrame:
    """Load action-outcome training rows from the local SQLite database."""
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        recommendations = conn.execute("SELECT * FROM recommendations").fetchall()
        outcomes = conn.execute("SELECT * FROM action_outcomes").fetchall()
    except sqlite3.Error:
        return pd.DataFrame()
    finally:
        conn.close()
    return build_action_outcome_dataset(
        [dict(row) for row in recommendations],
        [dict(row) for row in outcomes],
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
