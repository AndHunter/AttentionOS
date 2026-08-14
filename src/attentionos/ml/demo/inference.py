"""Real-time demo inference over current local SQLite telemetry."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from attentionos.config import get_config
from attentionos.ml.demo.features import feature_schema, real_events_to_frame, build_features_at
from attentionos.ml.demo.recommendation_engine import recommend_action


def run_demo_inference(
    db_path: Path | None = None,
    model_dir: Path = Path("models/demo"),
    min_minutes: int = 30,
) -> dict[str, object]:
    started = time.perf_counter()
    config = get_config()
    db = db_path or config.db_path
    events = _load_recent_events(db)
    if not events:
        return _warmup("No telemetry yet", started)
    frame = real_events_to_frame(events)
    active_minutes = float(frame["active"].sum() * _resolution_minutes(frame))
    if active_minutes < min_minutes:
        return _warmup("Collecting data", started, active_minutes)
    row = build_features_at(frame, frame["timestamp"].max())
    models = _load_models(model_dir)
    if models is None:
        return _warmup("Demo model not trained", started, active_minutes)

    metadata, eff, decline, benefit = models
    schema = feature_schema()
    x = pd.DataFrame([{name: row.get(name, 0.0) for name in schema.all}])
    current_effectiveness = float(np.clip(eff.predict(x)[0], 1, 5))
    decline_probability = float(np.clip(decline.predict_proba(x)[0][1], 0, 1))
    break_benefit = float(np.clip(benefit.predict(x)[0], 0, 1))
    recommendation = recommend_action(
        current_effectiveness=current_effectiveness,
        decline_probability=decline_probability,
        break_benefit=break_benefit,
        continuous_work_minutes=float(row["continuous_work_minutes"]),
        time_since_last_break=float(row["time_since_last_break"]),
        workload_last_4h=float(row["workload_last_4h"]),
    )
    return {
        "mode": "demo",
        "status": "ready",
        "disclaimer": "Demo model trained on synthetic data.",
        "disclaimer_ru": "Демо-модель обучена на синтетических данных.",
        "model_version": metadata.get("model_version", "demo-v1"),
        "current_effectiveness": current_effectiveness,
        "decline_probability": decline_probability,
        "break_benefit": break_benefit,
        "recommendation": recommendation.__dict__,
        "signals": _signals(row),
        "active_minutes": active_minutes,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "metadata": {
            "samples": metadata.get("samples", 0),
            "metrics": metadata.get("metrics", {}),
            "feature_importance": metadata.get("feature_importance", {}),
        },
    }


def _load_models(model_dir: Path):
    metadata_path = model_dir / "metadata.json"
    if not metadata_path.exists():
        return None
    from catboost import CatBoostClassifier, CatBoostRegressor

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    eff = CatBoostRegressor()
    eff.load_model(model_dir / "effectiveness.cbm")
    decline = CatBoostClassifier()
    decline.load_model(model_dir / "decline.cbm")
    benefit = CatBoostRegressor()
    benefit.load_model(model_dir / "break_benefit.cbm")
    return metadata, eff, decline, benefit


def _load_recent_events(db_path: Path) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    since = datetime.utcnow() - timedelta(hours=12)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT ts_start, ts_end, process_name, idle_seconds, keyboard_events, mouse_events, task_label "
        "FROM activity_events WHERE ts_start >= ? ORDER BY ts_start ASC",
        (since.isoformat(sep=" "),),
    ).fetchall()
    return [dict(row) for row in rows]


def _warmup(reason: str, started: float, active_minutes: float = 0.0) -> dict[str, object]:
    return {
        "mode": "demo",
        "status": "warmup",
        "reason": reason,
        "disclaimer": "Demo model trained on synthetic data.",
        "disclaimer_ru": "Демо-модель обучена на синтетических данных.",
        "active_minutes": active_minutes,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _resolution_minutes(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 1.0
    diffs = df["timestamp"].sort_values().diff().dropna().dt.total_seconds() / 60
    return float(diffs.median()) if not diffs.empty else 1.0


def _signals(row: dict[str, object]) -> list[dict[str, object]]:
    keys = [
        "session_duration_vs_baseline",
        "switch_rate_delta_5_30",
        "input_rate_slope_30m",
        "active_ratio_vs_baseline",
        "workload_last_4h",
    ]
    return [{"name": key, "value": round(float(row.get(key, 0.0)), 3)} for key in keys]


def main() -> None:
    print(json.dumps(run_demo_inference(), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

