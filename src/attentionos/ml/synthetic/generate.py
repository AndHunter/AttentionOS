"""CLI for generating separated synthetic demo ML datasets."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from attentionos.ml.demo.features import build_training_windows
from attentionos.ml.synthetic.state_simulator import simulate_user_day
from attentionos.ml.synthetic.user_profiles import sample_profiles


def generate_dataset(
    output_dir: Path,
    users: int,
    days: int,
    seed: int,
    resolution_seconds: int,
    step_minutes: int,
) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    profiles = sample_profiles(users, seed)
    start = datetime(2026, 1, 1)
    telemetry_rows: list[dict[str, object]] = []
    report_rows: list[dict[str, object]] = []
    intervention_rows: list[dict[str, object]] = []
    for profile in profiles:
        for day in range(days):
            telemetry, reports, interventions = simulate_user_day(
                profile, day, start, resolution_seconds, rng
            )
            telemetry_rows.extend(telemetry)
            report_rows.extend(reports)
            intervention_rows.extend(interventions)

    telemetry_df = pd.DataFrame(telemetry_rows)
    reports_df = pd.DataFrame(report_rows)
    interventions_df = pd.DataFrame(intervention_rows)
    training = build_training_windows(telemetry_df, step_minutes=step_minutes)
    training = _attach_targets(training, telemetry_df, reports_df)

    telemetry_df.to_parquet(output_dir / "synthetic_telemetry.parquet", index=False)
    reports_df.to_parquet(output_dir / "synthetic_reports.parquet", index=False)
    interventions_df.to_parquet(output_dir / "synthetic_interventions.parquet", index=False)
    training.to_parquet(output_dir / "synthetic_training_dataset.parquet", index=False)

    metadata = {
        "dataset_version": "synthetic-demo-v1",
        "seed": seed,
        "users": users,
        "days": days,
        "resolution_seconds": resolution_seconds,
        "step_minutes": step_minutes,
        "telemetry_rows": int(len(telemetry_df)),
        "reports": int(len(reports_df)),
        "interventions": int(len(interventions_df)),
        "training_samples": int(len(training)),
        "created_at": datetime.now().isoformat(),
        "note": "Demo model trained on synthetic data. Synthetic metrics are not real-world validation.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    _write_quality_report(output_dir, telemetry_df, reports_df, training, metadata)
    return metadata


def _attach_targets(features: pd.DataFrame, telemetry: pd.DataFrame, reports: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return features
    telemetry = telemetry.copy()
    telemetry["timestamp"] = pd.to_datetime(telemetry["timestamp"])
    reports = reports.copy()
    reports["timestamp"] = pd.to_datetime(reports["timestamp"])
    features = features.copy()
    features["timestamp"] = pd.to_datetime(features["timestamp"])
    features["current_effectiveness_target"] = np.nan
    features["decline_next_30m"] = 0
    features["break_benefit_score"] = 0.0
    features["latent_effectiveness_eval"] = np.nan

    for index, row in features.iterrows():
        user = row["user_id"]
        at = row["timestamp"]
        user_tel = telemetry[(telemetry["user_id"] == user) & (telemetry["timestamp"] <= at)]
        future = telemetry[
            (telemetry["user_id"] == user)
            & (telemetry["timestamp"] > at)
            & (telemetry["timestamp"] <= at + pd.Timedelta(minutes=30))
        ]
        user_reports = reports[
            (reports["user_id"] == user)
            & (reports["timestamp"] >= at - pd.Timedelta(minutes=20))
            & (reports["timestamp"] <= at + pd.Timedelta(minutes=20))
        ]
        if not user_reports.empty:
            features.at[index, "current_effectiveness_target"] = float(user_reports.iloc[0]["effectiveness"])
        elif not user_tel.empty:
            latent = float(user_tel.iloc[-1]["latent_effectiveness"])
            features.at[index, "current_effectiveness_target"] = float(np.clip(round(latent * 4 + 1), 1, 5))
        if not user_tel.empty:
            now_eff = float(user_tel.iloc[-1]["latent_effectiveness"])
            features.at[index, "latent_effectiveness_eval"] = now_eff
            if not future.empty:
                future_eff = float(future["latent_effectiveness"].tail(max(len(future) // 4, 1)).mean())
                features.at[index, "decline_next_30m"] = int(now_eff - future_eff >= 0.12)
                continuous = float(row.get("continuous_work_minutes", 0))
                fatigue = float(user_tel.iloc[-1]["latent_fatigue"])
                features.at[index, "break_benefit_score"] = float(
                    np.clip(0.18 * (continuous / 120) + 0.45 * fatigue - 0.08 * now_eff, 0, 1)
                )
    return features.dropna(subset=["current_effectiveness_target"])


def _write_quality_report(
    output_dir: Path,
    telemetry: pd.DataFrame,
    reports: pd.DataFrame,
    training: pd.DataFrame,
    metadata: dict[str, object],
) -> None:
    report = {
        "metadata": metadata,
        "target_distribution": training["current_effectiveness_target"].value_counts().sort_index().to_dict()
        if not training.empty
        else {},
        "decline_rate": float(training["decline_next_30m"].mean()) if not training.empty else 0.0,
        "break_benefit_mean": float(training["break_benefit_score"].mean()) if not training.empty else 0.0,
        "archetypes": telemetry["archetype"].value_counts().to_dict() if not telemetry.empty else {},
        "tasks": telemetry["task_category"].value_counts().to_dict() if not telemetry.empty else {},
        "reports_per_user_mean": float(reports.groupby("user_id").size().mean()) if not reports.empty else 0.0,
        "hour_distribution": pd.to_datetime(telemetry["timestamp"]).dt.hour.value_counts().sort_index().to_dict()
        if not telemetry.empty
        else {},
    }
    analysis_dir = Path("artifacts/demo_analysis")
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "synthetic_quality_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("data/demo"))
    parser.add_argument("--users", type=int, default=40)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resolution-seconds", type=int, default=60)
    parser.add_argument("--step-minutes", type=int, default=5)
    args = parser.parse_args()
    metadata = generate_dataset(
        args.output_dir,
        args.users,
        args.days,
        args.seed,
        args.resolution_seconds,
        args.step_minutes,
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()

