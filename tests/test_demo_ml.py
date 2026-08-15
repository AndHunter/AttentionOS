from __future__ import annotations

import pandas as pd

from attentionos.ml.demo.features import build_features_at, build_training_windows, feature_schema
from attentionos.ml.demo.recommendation_engine import recommend_action
from attentionos.ml.synthetic.generate import generate_dataset


def test_synthetic_generator_reproducible(tmp_path) -> None:
    first = generate_dataset(tmp_path / "a", users=2, days=1, seed=123, resolution_seconds=300, step_minutes=15)
    second = generate_dataset(tmp_path / "b", users=2, days=1, seed=123, resolution_seconds=300, step_minutes=15)
    assert first["training_samples"] == second["training_samples"]
    a = pd.read_parquet(tmp_path / "a" / "synthetic_training_dataset.parquet")
    b = pd.read_parquet(tmp_path / "b" / "synthetic_training_dataset.parquet")
    pd.testing.assert_frame_equal(a.head(10).reset_index(drop=True), b.head(10).reset_index(drop=True))


def test_rolling_features_and_no_future_leakage() -> None:
    start = pd.Timestamp("2026-01-01 09:00:00")
    rows = []
    for idx in range(12):
        rows.append(
            {
                "user_id": "u1",
                "day": 0,
                "timestamp": start + pd.Timedelta(minutes=idx * 5),
                "app": "Code.exe" if idx < 6 else "Chrome.exe",
                "task_category": "coding",
                "difficulty": 3,
                "active": 1,
                "idle": 0,
                "keyboard_events": 10 + idx,
                "mouse_events": 5,
                "is_distraction": 0,
            }
        )
    events = pd.DataFrame(rows)
    before_future = build_features_at(events, start + pd.Timedelta(minutes=25))
    after_future = build_features_at(events.iloc[:6], start + pd.Timedelta(minutes=25))
    assert before_future["switch_count_30m"] == after_future["switch_count_30m"]
    assert "keyboard_rate_delta_5_30" in before_future
    assert "time_of_day_sin" in before_future


def test_feature_schema_has_required_demo_features() -> None:
    names = set(feature_schema().all)
    assert {"active_ratio_1m", "active_ratio_5m", "active_ratio_15m", "active_ratio_30m", "active_ratio_60m", "active_ratio_120m"} <= names
    assert {"input_rate_delta_1_15", "input_rate_delta_5_30", "input_rate_slope_30m", "switch_rate_vs_baseline"} <= names
    assert {"work_episode_elapsed_minutes", "break_count_today", "last_break_duration"} <= names
    assert "task_category" in names


def test_recommendation_sanity_scenarios() -> None:
    stable = recommend_action(4.0, 0.08, 0.12, 0.18, 0.12, 30, 30, 60)
    long = recommend_action(2.2, 0.70, 0.78, 0.86, 0.72, 150, 150, 260)
    after_break = recommend_action(3.5, 0.12, 0.22, 0.28, 0.16, 18, 18, 120)
    assert stable.action == "CONTINUE"
    assert long.state == "BREAK_RECOMMENDED"
    assert long.policy_source == "FALLBACK"
    assert long.action.startswith("BREAK")
    assert after_break.action == "CONTINUE"


def test_soft_decline_can_trigger_break() -> None:
    result = recommend_action(
        3.0,
        0.40,
        0.50,
        0.62,
        0.45,
        100,
        100,
        180,
        input_rate_delta_5_30=-1.0,
        switch_rate_delta_5_30=0.4,
        idle_ratio_delta_5_30=0.3,
        session_duration_vs_baseline=2.2,
    )
    assert result.state == "BREAK_RECOMMENDED"
    assert result.break_benefit >= 5.5
