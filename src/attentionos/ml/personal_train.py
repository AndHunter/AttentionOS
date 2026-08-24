"""Train a small personal effectiveness calibrator from real local data."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from attentionos.config import get_config
from attentionos.ml.demo.features import build_features_at, feature_schema, real_events_to_frame

DEFAULT_MIN_SAMPLES = 5
MAX_TRAINING_REPORTS = 20
MAX_TRAINING_DAYS = 7
MAX_TELEMETRY_LOOKBACK_HOURS = 4
MAX_TELEMETRY_ROWS = 20_000
MODEL_VERSION = "personal-effectiveness-v1"


@dataclass(frozen=True)
class PersonalTrainingResult:
    status: str
    samples: int
    model_version: str
    model_dir: str
    validation_mae: float | None
    message: str


def train_personal_effectiveness(
    db_path: Path | None = None,
    model_dir: Path | None = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> PersonalTrainingResult:
    """Train on real telemetry/self-reports without mixing synthetic rows."""
    config = get_config()
    db = db_path or config.db_path
    target_dir = model_dir or (config.data_dir / "models" / "personal_effectiveness")
    rows = _build_rows(db)
    target_dir.mkdir(parents=True, exist_ok=True)
    if len(rows) < min_samples:
        result = PersonalTrainingResult(
            status="insufficient_data",
            samples=len(rows),
            model_version=MODEL_VERSION,
            model_dir=str(target_dir),
            validation_mae=None,
            message=f"Need {min_samples} self-reports with telemetry windows, got {len(rows)}.",
        )
        _write_metadata(target_dir, result, feature_schema().all)
        return result

    dataset = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    features = feature_schema().all
    train_df, valid_df = _chronological_split(dataset)
    x_train = train_df[features].fillna(0.0)
    y_train = train_df["target_effectiveness"].astype(float)
    x_valid = valid_df[features].fillna(0.0)
    y_valid = valid_df["target_effectiveness"].astype(float)

    from catboost import CatBoostRegressor, Pool

    cat_features = [
        features.index(name)
        for name in feature_schema().categorical
        if name in features
    ]
    model = CatBoostRegressor(
        iterations=120,
        depth=4,
        learning_rate=0.05,
        loss_function="RMSE",
        random_seed=42,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(Pool(x_train, y_train, cat_features=cat_features))
    validation_mae = None
    if len(valid_df) > 0:
        predicted = np.clip(model.predict(Pool(x_valid, cat_features=cat_features)), 1, 5)
        validation_mae = float(np.mean(np.abs(predicted - y_valid.to_numpy())))
    model.save_model(target_dir / "effectiveness.cbm")
    result = PersonalTrainingResult(
        status="trained",
        samples=len(dataset),
        model_version=MODEL_VERSION,
        model_dir=str(target_dir),
        validation_mae=validation_mae,
        message="Personal effectiveness calibrator trained on local real telemetry.",
    )
    _write_metadata(target_dir, result, features)
    return result


def load_personal_effectiveness(model_dir: Path | None = None):
    config = get_config()
    target_dir = model_dir or (config.data_dir / "models" / "personal_effectiveness")
    metadata_path = target_dir / "metadata.json"
    model_path = target_dir / "effectiveness.cbm"
    if not metadata_path.exists() or not model_path.exists():
        return None
    from catboost import CatBoostRegressor

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "trained":
        return None
    model = CatBoostRegressor()
    model.load_model(model_path)
    return metadata, model


def _build_rows(db_path: Path) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        report_rows = conn.execute(
            "SELECT id, timestamp, perceived_effectiveness, perceived_fatigue, "
            "task_difficulty, task_name "
            "FROM self_reports ORDER BY timestamp DESC LIMIT ?1",
            (MAX_TRAINING_REPORTS,),
        ).fetchall()
        report_rows = sorted(report_rows, key=lambda row: row["timestamp"])
        if not report_rows:
            return []
        latest_report = datetime.fromisoformat(str(report_rows[-1]["timestamp"]))
        report_cutoff = latest_report - timedelta(days=MAX_TRAINING_DAYS)
        report_rows = [
            row
            for row in report_rows
            if datetime.fromisoformat(str(row["timestamp"])) >= report_cutoff
        ]
        if not report_rows:
            return []
        earliest = datetime.fromisoformat(str(report_rows[0]["timestamp"])) - timedelta(
            hours=MAX_TELEMETRY_LOOKBACK_HOURS
        )
        event_rows = conn.execute(
            "SELECT * FROM ("
            "SELECT ts_start, ts_end, process_name, idle_seconds, keyboard_events, "
            "mouse_events, task_label "
            "FROM activity_events WHERE ts_start >= ?1 ORDER BY ts_start DESC LIMIT ?2"
            ") ORDER BY ts_start ASC",
            (earliest.isoformat(sep=" "), MAX_TELEMETRY_ROWS),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    if not event_rows or not report_rows:
        return []
    frame = _downsample_frame(real_events_to_frame([dict(row) for row in event_rows]))
    if frame.empty:
        return []
    rows: list[dict[str, object]] = []
    frame_timestamps = pd.to_datetime(frame["timestamp"])
    for report in report_rows:
        at = _to_local_timestamp(report["timestamp"])
        window_start = at - pd.Timedelta(hours=MAX_TELEMETRY_LOOKBACK_HOURS)
        causal = frame[(frame_timestamps >= window_start) & (frame_timestamps <= at)]
        if len(causal) < 10:
            continue
        row = build_features_at(causal, at)
        task = _normalize_task(str(report["task_name"] or row.get("task_category") or "other"))
        row["task_category"] = task
        row["timestamp"] = at.isoformat()
        row["report_id"] = int(report["id"] or 0)
        row["target_effectiveness"] = float(report["perceived_effectiveness"] or 3)
        row["target_fatigue"] = float(report["perceived_fatigue"] or 3)
        row["target_difficulty"] = float(report["task_difficulty"] or 3)
        rows.append(row)
    return rows


def _normalize_task(task: str) -> str:
    value = task.lower()
    mapping = {
        "работа": "work",
        "учёба": "study",
        "учеба": "study",
        "уроки": "study",
        "домашка": "study",
        "отдых": "rest",
        "игра": "gaming",
        "другое": "other",
        "программирование": "coding",
        "математика": "math",
        "физика": "science",
        "химия": "science",
        "биология": "science",
        "английский": "english",
        "другой язык": "english",
        "чтение": "reading",
        "письмо": "writing",
        "исследование": "research",
        "творчество": "creative",
        "общение": "communication",
        "админка": "admin",
        "планирование": "admin",
    }
    normalized = mapping.get(value, value)
    if normalized in {"school", "homework"}:
        return "study"
    if normalized in {"physics", "chemistry", "biology"}:
        return "science"
    if normalized in {"language"}:
        return "english"
    if normalized in {"planning"}:
        return "admin"
    return normalized


def _downsample_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    indexed = frame.copy()
    indexed["timestamp"] = pd.to_datetime(indexed["timestamp"])
    indexed = indexed.sort_values("timestamp").set_index("timestamp")
    grouped = indexed.resample("1min").agg(
        {
            "user_id": "last",
            "day": "last",
            "app": "last",
            "task_category": "last",
            "difficulty": "mean",
            "active": "max",
            "idle": "max",
            "keyboard_events": "sum",
            "mouse_events": "sum",
            "is_distraction": "max",
        }
    )
    grouped = grouped.dropna(subset=["app"]).reset_index()
    grouped["day"] = grouped["timestamp"].dt.date.astype(str)
    return grouped


def _to_local_timestamp(value: object) -> pd.Timestamp:
    ts = pd.to_datetime(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    local_tz = datetime.now().astimezone().tzinfo
    return ts.tz_convert(local_tz).tz_localize(None)


def _chronological_split(dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(dataset) < 8:
        return dataset.copy(), dataset.iloc[0:0].copy()
    split_at = max(int(len(dataset) * 0.8), 1)
    return dataset.iloc[:split_at].copy(), dataset.iloc[split_at:].copy()


def _write_metadata(target_dir: Path, result: PersonalTrainingResult, features: list[str]) -> None:
    metadata = {
        **asdict(result),
        "features": features,
        "trained_at_utc": datetime.now(UTC).isoformat(),
        "source": "real_local_telemetry",
    }
    (target_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    min_samples = DEFAULT_MIN_SAMPLES
    if "--min-samples" in sys.argv:
        index = sys.argv.index("--min-samples")
        min_samples = int(sys.argv[index + 1])
    result = train_personal_effectiveness(min_samples=min_samples)
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
