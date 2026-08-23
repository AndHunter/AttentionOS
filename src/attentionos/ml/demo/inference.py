"""Real-time demo inference over current local SQLite telemetry."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from attentionos.config import get_config
from attentionos.ml.demo.features import build_features_at, feature_schema, real_events_to_frame
from attentionos.ml.demo.recommendation_engine import recommend_action
from attentionos.ml.personal_train import load_personal_effectiveness

INFERENCE_INTERVAL_SECONDS = 60
MIN_WORK_RECOMMENDATION_HOLD_MINUTES = 15
POST_BREAK_WORK_GRACE_MINUTES = 20


def run_demo_inference(
    db_path: Path | None = None,
    model_dir: Path | None = None,
    min_minutes: int = 30,
    persist: bool = True,
) -> dict[str, object]:
    started = time.perf_counter()
    now_local = datetime.now().astimezone()
    config = get_config()
    db = db_path or config.db_path
    diagnostics = _diagnostics(now_local, db)
    try:
        events = _load_recent_events(db, now_local)
        diagnostics["feature_rows_available"] = len(events)
        diagnostics["telemetry_available_minutes"] = round(_telemetry_span_minutes(events), 2)
        if not events:
            return _warmup("Нет telemetry за последние 24 часа.", started, diagnostics)
        raw_frame = real_events_to_frame(events)
        active_minutes = float(raw_frame["active"].sum() * _resolution_minutes(raw_frame))
        frame = _compact_inference_frame(raw_frame)
        diagnostics["active_minutes"] = round(active_minutes, 2)
        telemetry_minutes = max(active_minutes, float(diagnostics["telemetry_available_minutes"]))
        if telemetry_minutes < min_minutes:
            diagnostics["warmup_reason"] = (
                f"Накоплено {telemetry_minutes:.0f} из {min_minutes} минут telemetry."
            )
            return _warmup(diagnostics["warmup_reason"], started, diagnostics, telemetry_minutes)

        row = build_features_at(frame, frame["timestamp"].max())
        diagnostics["feature_vector_valid"] = True
        resolved_model_dir = _resolve_model_dir(model_dir)
        diagnostics["model_path"] = str(resolved_model_dir) if resolved_model_dir else None
        models = _load_models(resolved_model_dir) if resolved_model_dir else None
        diagnostics["model_loaded"] = models is not None
        if models is None:
            diagnostics["warmup_reason"] = (
                "DEMO model files are missing; train or package models/demo."
            )
            return _warmup("DEMO model files are missing.", started, diagnostics, telemetry_minutes)

        metadata, eff, decline, benefit = models
        diagnostics["model_version"] = metadata.get("model_version", "demo-v1")
        model_features = list(metadata.get("features") or feature_schema().all)
        x = pd.DataFrame([{name: row.get(name, 0.0) for name in model_features}])
        current_effectiveness_raw = float(np.clip(eff.predict(x)[0], 1, 5))
        personal = _predict_personal_effectiveness(row)
        if personal is not None:
            personal_raw, personal_weight, personal_version = personal
            current_effectiveness_raw = float(
                np.clip(
                    current_effectiveness_raw * (1 - personal_weight)
                    + personal_raw * personal_weight,
                    1,
                    5,
                )
            )
            diagnostics["personal_model_loaded"] = True
            diagnostics["personal_model_version"] = personal_version
            diagnostics["personal_model_weight"] = round(personal_weight, 3)
        else:
            diagnostics["personal_model_loaded"] = False
        effectiveness = _effectiveness_to_100(current_effectiveness_raw)
        decline_base = float(np.clip(decline.predict_proba(x)[0][1], 0, 1))
        trend_pressure = _trend_pressure(row)
        decline_15m = float(np.clip(decline_base * 0.72 + trend_pressure * 0.10, 0, 1))
        decline_30m = float(np.clip(decline_base + trend_pressure * 0.08, 0, 1))
        decline_60m = float(
            np.clip(
                decline_base * 1.18
                + trend_pressure * 0.14
                + float(row["continuous_work_minutes"]) / 600,
                0,
                1,
            )
        )
        raw_break_benefit = float(np.clip(benefit.predict(x)[0], 0, 1))
        recommendation = recommend_action(
            current_effectiveness=current_effectiveness_raw,
            decline_15m=decline_15m,
            decline_30m=decline_30m,
            decline_60m=decline_60m,
            raw_break_benefit=raw_break_benefit,
            continuous_work_minutes=float(row["continuous_work_minutes"]),
            time_since_last_break=float(row["time_since_last_break"]),
            workload_last_4h=float(row["workload_last_4h"]),
            input_rate_delta_5_30=float(row["input_rate_delta_5_30"]),
            switch_rate_delta_5_30=float(row["switch_rate_delta_5_30"]),
            idle_ratio_delta_5_30=float(row["idle_ratio_delta_5_30"]),
            session_duration_vs_baseline=float(row["session_duration_vs_baseline"]),
            break_count_today=float(row["break_count_today"]),
            last_break_duration=float(row["last_break_duration"]),
            active_ratio_15m=float(row["active_ratio_15m"]),
            idle_ratio_15m=float(row["idle_ratio_15m"]),
        )
        tracking_started_at = _tracking_started_at(db)
        tracking_elapsed = _tracking_elapsed_minutes(tracking_started_at, now_local)
        break_lock = _active_break_lock(db, now_local, tracking_started_at)
        if break_lock is not None:
            lock_state = str(break_lock.get("state") or "BREAK_RECOMMENDED")
            recommendation = replace(
                recommendation,
                action=break_lock["action"],
                state=lock_state,  # type: ignore[arg-type]
                title="Break in progress" if lock_state == "BREAK" else "Break recommended",
                reason=f"break_lock: recommendation is held until {break_lock['until_local']}.",
                confidence=max(recommendation.confidence, 0.9),
                recommended_break_minutes=break_lock["minutes"],
                break_benefit=max(recommendation.break_benefit, float(break_lock["benefit"])),
                next_break_eta_minutes=0,
                policy_source="FALLBACK",
            )
        elif post_break_grace := _post_break_work_grace(db, now_local):
            recommendation = replace(
                recommendation,
                action="CONTINUE",
                state="WORK",
                title="Work",
                reason=(
                    "post_break_grace: stable work recommendation until "
                    f"{post_break_grace['until_local']}."
                ),
                confidence=max(recommendation.confidence, 0.86),
                recommended_break_minutes=None,
                next_break_eta_minutes=post_break_grace["remaining_minutes"],
                policy_source="FALLBACK",
            )
        elif tracking_elapsed is not None and tracking_elapsed < 30:
            recommendation = replace(
                recommendation,
                action="CONTINUE",
                state="WORK",
                title="Work",
                reason=(
                    f"fresh_tracking_start: only {tracking_elapsed:.0f} minutes since "
                    "Start Tracking."
                ),
                confidence=max(recommendation.confidence, 0.82),
                recommended_break_minutes=None,
                next_break_eta_minutes=5,
                policy_source="FALLBACK",
            )
        elif (
            recommendation.state == "BREAK_RECOMMENDED"
            and (work_hold := _active_work_hold(db, now_local)) is not None
            and not _should_override_work_hold(recommendation, decline_15m, decline_60m)
        ):
            recommendation = replace(
                recommendation,
                action="CONTINUE",
                state="WORK",
                title="Work",
                reason=(
                    "work_hysteresis: keeping WORK until "
                    f"{work_hold['until_local']} before changing recommendation."
                ),
                confidence=max(0.72, 1.0 - decline_30m),
                recommended_break_minutes=None,
                next_break_eta_minutes=work_hold["remaining_minutes"],
                policy_source="FALLBACK",
            )
        result = {
            "mode": "demo",
            "status": "ready",
            "state": recommendation.state,
            "disclaimer": "Demo model trained on synthetic data.",
            "disclaimer_ru": "Демо-модель обучена на синтетических данных.",
            "model_version": diagnostics["model_version"],
            "current_effectiveness": round(effectiveness, 1),
            "current_effectiveness_raw": round(current_effectiveness_raw, 3),
            "decline_15m": round(decline_15m, 4),
            "decline_30m": round(decline_30m, 4),
            "decline_60m": round(decline_60m, 4),
            "decline_probability": round(decline_30m, 4),
            "break_benefit": recommendation.break_benefit,
            "recommended_action": recommendation.action,
            "recommended_break_minutes": recommendation.recommended_break_minutes,
            "next_break_eta_minutes": recommendation.next_break_eta_minutes,
            "policy_source": recommendation.policy_source,
            "recommendation": recommendation.__dict__,
            "signals": _signals(row),
            "active_minutes": round(active_minutes, 2),
            "telemetry_available_minutes": diagnostics["telemetry_available_minutes"],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "diagnostics": diagnostics,
            "metadata": {
                "samples": metadata.get("samples", 0),
                "metrics": metadata.get("metrics", {}),
                "feature_importance": metadata.get("feature_importance", {}),
            },
        }
        if persist:
            _persist_prediction(db, result, now_local)
        return result
    except Exception as err:  # noqa: BLE001 - this path is surfaced in diagnostics, not swallowed.
        diagnostics["last_inference_error"] = repr(err)
        return _warmup("ML inference error; see diagnostics.", started, diagnostics)


def _resolve_model_dir(model_dir: Path | None) -> Path | None:
    candidates: list[Path] = []
    if model_dir is not None:
        candidates.append(model_dir)
    candidates.append(Path("models/demo"))
    here = Path(__file__).resolve()
    candidates.extend(parent / "models" / "demo" for parent in here.parents)
    for candidate in candidates:
        if (candidate / "metadata.json").exists():
            return candidate.resolve()
    return None


def _load_models(model_dir: Path | None):
    if model_dir is None:
        return None
    metadata_path = model_dir / "metadata.json"
    model_paths = [
        metadata_path,
        model_dir / "effectiveness.cbm",
        model_dir / "decline.cbm",
        model_dir / "break_benefit.cbm",
    ]
    if not all(path.exists() for path in model_paths):
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


def _predict_personal_effectiveness(row: dict[str, object]) -> tuple[float, float, str] | None:
    personal = load_personal_effectiveness()
    if personal is None:
        return None
    metadata, model = personal
    features = list(metadata.get("features") or feature_schema().all)
    x = pd.DataFrame([{name: row.get(name, 0.0) for name in features}])
    samples = int(metadata.get("samples") or 0)
    weight = float(np.clip(samples / 80, 0.08, 0.35))
    prediction = float(np.clip(model.predict(x)[0], 1, 5))
    return prediction, weight, str(metadata.get("model_version") or "personal-effectiveness-v1")


def _load_recent_events(db_path: Path, now_local: datetime) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    since_local = now_local - timedelta(hours=24)
    since_utc = since_local.astimezone(UTC).replace(tzinfo=None)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT ts_start, ts_end, process_name, idle_seconds, keyboard_events, "
        "mouse_events, task_label "
        "FROM activity_events WHERE ts_start >= ? ORDER BY ts_start ASC",
        (since_utc.isoformat(sep=" "),),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _compact_inference_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if len(frame) <= 4_000:
        return frame
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"])
    cutoff = data["timestamp"].max() - pd.Timedelta(minutes=30)
    recent = data[data["timestamp"] >= cutoff]
    old = data[data["timestamp"] < cutoff]
    if old.empty:
        return data
    old_agg = (
        old.sort_values("timestamp")
        .set_index("timestamp")
        .resample("1min")
        .agg(
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
        .dropna(subset=["app"])
        .reset_index()
    )
    old_agg["day"] = old_agg["timestamp"].dt.date.astype(str)
    return (
        pd.concat([old_agg, recent], ignore_index=True)
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _persist_prediction(db_path: Path, result: dict[str, object], now_local: datetime) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        _ensure_ml_tables(conn)
        now_utc = now_local.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ")
        rec = result["recommendation"]
        assert isinstance(rec, dict)
        previous_action = _previous_prediction_action(conn)
        cooldown_minutes = _notification_cooldown_minutes()
        runtime_break_state = _runtime_value(conn, "break_state")
        notifications_enabled = _model_notifications_enabled()
        should_notify_break = (
            notifications_enabled
            and
            result.get("state") == "BREAK_RECOMMENDED"
            and runtime_break_state != "BREAK"
            and not previous_action.startswith("BREAK")
            and not _break_notification_in_cooldown(conn, now_utc, cooldown_minutes)
            and not _break_recommendation_ignored(conn, now_utc)
        )
        should_notify_work = (
            notifications_enabled
            and
            result.get("state") == "WORK"
            and previous_action.startswith("BREAK")
            and result.get("recommended_action") == "CONTINUE"
            and not _notification_in_cooldown(
                conn,
                "ml_ready_to_work",
                now_utc,
                max(5, cooldown_minutes),
            )
        )
        conn.execute(
            "INSERT INTO ml_predictions ("
            "timestamp, model_version, effectiveness, decline_15m, decline_30m, decline_60m, "
            "continue_utility, best_break_utility, break_benefit, recommended_action, "
            "recommended_break_minutes, next_break_eta, confidence, policy_source, "
            "candidate_utilities, diagnostics_json"
            ") VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)",
            (
                now_utc,
                result.get("model_version"),
                result.get("current_effectiveness"),
                result.get("decline_15m"),
                result.get("decline_30m"),
                result.get("decline_60m"),
                rec.get("continue_utility"),
                rec.get("best_break_utility"),
                result.get("break_benefit"),
                result.get("recommended_action"),
                result.get("recommended_break_minutes"),
                result.get("next_break_eta_minutes"),
                rec.get("confidence"),
                result.get("policy_source"),
                json.dumps(rec.get("utilities") or {}, ensure_ascii=False),
                json.dumps(result.get("diagnostics") or {}, ensure_ascii=False, default=str),
            ),
        )
        _persist_work_hold_state(conn, result, rec, now_local)
        if should_notify_break:
            minutes = result.get("recommended_break_minutes") or 10
            benefit = result.get("break_benefit") or 0
            body = (
                "Пора сделать перерыв. "
                f"Рекомендуемая длительность: {minutes} мин. "
                f"Польза перерыва: {benefit}/10."
            )
            conn.execute(
                "INSERT INTO recommendations ("
                "timestamp, recommended_action, recommended_duration, accepted"
                ") "
                "VALUES (?1, ?2, ?3, 0)",
                (now_utc, result.get("recommended_action"), minutes),
            )
            payload = json.dumps(
                {"source": "demo_ml", "prediction": result.get("recommended_action")}
            )
            conn.execute(
                "INSERT INTO notifications ("
                "created_at, title, body, state, intervention_id, kind, action_payload"
                ") "
                "VALUES (?1, 'AttentionOS', ?2, 'unread', NULL, 'ml_break_recommendation', ?3)",
                (now_utc, body, payload),
            )
        elif should_notify_work:
            body = "Можно возвращаться к работе. Перерыв завершён, состояние переоценено."
            payload = json.dumps(
                {"source": "demo_ml", "prediction": result.get("recommended_action")}
            )
            conn.execute(
                "INSERT INTO notifications ("
                "created_at, title, body, state, intervention_id, kind, action_payload"
                ") "
                "VALUES (?1, 'AttentionOS', ?2, 'unread', NULL, 'ml_ready_to_work', ?3)",
                (now_utc, body, payload),
            )
        conn.commit()
    finally:
        conn.close()


def _ensure_ml_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_runtime_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ml_predictions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, "
        "model_version TEXT, effectiveness REAL, decline_15m REAL, decline_30m REAL, "
        "decline_60m REAL, continue_utility REAL, best_break_utility REAL, "
        "break_benefit REAL, recommended_action TEXT, recommended_break_minutes INTEGER, "
        "next_break_eta INTEGER, "
        "confidence REAL, policy_source TEXT, candidate_utilities TEXT, diagnostics_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recommendations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, recommended_action TEXT, "
        "recommended_duration INTEGER, accepted INTEGER DEFAULT 0, ignored INTEGER DEFAULT 0, "
        "started_at TEXT, completed_at TEXT, ignored_at TEXT, actual_duration REAL, "
        "prediction_before_id INTEGER, prediction_after_id INTEGER, task_before TEXT, "
        "task_after TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recommendation_outcomes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, recommendation_id INTEGER, "
        "created_at TEXT NOT NULL, action TEXT, accepted INTEGER DEFAULT 0, "
        "ignored INTEGER DEFAULT 0, planned_duration INTEGER, "
        "actual_duration REAL, prediction_before_id INTEGER, prediction_after_id INTEGER, "
        "effectiveness_before REAL, effectiveness_after REAL, decline_30m_before REAL, "
        "decline_30m_after REAL, task_before TEXT, task_after TEXT, "
        "active_minutes_during_break REAL, idle_minutes_during_break REAL, "
        "rest_task_minutes_during_break REAL, restful_break_score REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notifications ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
        "title TEXT NOT NULL, body TEXT NOT NULL, "
        "state TEXT NOT NULL, intervention_id INTEGER, kind TEXT NOT NULL, action_payload TEXT)"
    )
    _ensure_column(conn, "ml_predictions", "candidate_utilities", "TEXT")
    _ensure_column(conn, "ml_predictions", "diagnostics_json", "TEXT")
    _ensure_column(conn, "recommendations", "ignored", "INTEGER DEFAULT 0")
    _ensure_column(conn, "recommendations", "ignored_at", "TEXT")
    _ensure_column(conn, "recommendations", "prediction_before_id", "INTEGER")
    _ensure_column(conn, "recommendations", "prediction_after_id", "INTEGER")
    _ensure_column(conn, "recommendations", "task_before", "TEXT")
    _ensure_column(conn, "recommendations", "task_after", "TEXT")
    _ensure_column(conn, "recommendation_outcomes", "active_minutes_during_break", "REAL")
    _ensure_column(conn, "recommendation_outcomes", "idle_minutes_during_break", "REAL")
    _ensure_column(conn, "recommendation_outcomes", "rest_task_minutes_during_break", "REAL")
    _ensure_column(conn, "recommendation_outcomes", "restful_break_score", "REAL")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _previous_prediction_action(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT recommended_action FROM ml_predictions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return ""
    return str(row[0] or "")


def _runtime_value(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute("SELECT value FROM app_runtime_state WHERE key = ?1", (key,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return str(row[0])


def _set_runtime_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _load_runtime_settings():
    from attentionos.settings import SettingsStore

    return SettingsStore(get_config().data_dir / "settings.json").load()


def _model_notifications_enabled() -> bool:
    try:
        return bool(_load_runtime_settings().notifications.break_recommendations)
    except Exception:
        return True


def _persist_work_hold_state(
    conn: sqlite3.Connection,
    result: dict[str, object],
    recommendation: dict[str, object],
    now_local: datetime,
) -> None:
    if result.get("state") == "BREAK_RECOMMENDED":
        conn.execute("DELETE FROM app_runtime_state WHERE key = 'work_hold_until'")
        return
    if result.get("state") != "WORK" or result.get("recommended_action") != "CONTINUE":
        return
    reason = str(recommendation.get("reason") or "")
    if reason.startswith(("work_hysteresis", "post_break_grace", "fresh_tracking_start")):
        return
    now_utc = now_local.astimezone(UTC)
    current_until = _parse_runtime_utc(_runtime_value(conn, "work_hold_until") or "")
    if current_until is not None and current_until > now_utc:
        return
    hold_minutes = _work_hold_minutes(result.get("next_break_eta_minutes"))
    until = now_utc + timedelta(minutes=hold_minutes)
    _set_runtime_value(
        conn,
        "work_hold_until",
        until.replace(tzinfo=None).isoformat(sep=" "),
    )


def _work_hold_minutes(next_break_eta: object) -> int:
    try:
        eta_minutes = int(next_break_eta or 0)
    except (TypeError, ValueError):
        eta_minutes = 0
    settings_interval_minutes = max(_runtime_check_interval_seconds() // 60, 1)
    return max(
        eta_minutes,
        settings_interval_minutes,
        MIN_WORK_RECOMMENDATION_HOLD_MINUTES,
    )


def _notification_cooldown_minutes() -> int:
    try:
        settings = _load_runtime_settings()
        return int(max(settings.notifications.minimum_interval_minutes, 5))
    except Exception:
        return int(get_config().intervention.cooldown_minutes)


def _runtime_check_interval_seconds() -> int:
    try:
        settings = _load_runtime_settings()
        return int(min(max(settings.notifications.live_check_interval_seconds, 60), 1800))
    except Exception:
        return INFERENCE_INTERVAL_SECONDS


def _break_notification_in_cooldown(
    conn: sqlite3.Connection,
    now_utc: str,
    cooldown_minutes: int,
) -> bool:
    return _notification_in_cooldown(conn, "ml_break_recommendation", now_utc, cooldown_minutes)


def _notification_in_cooldown(
    conn: sqlite3.Connection,
    kind: str,
    now_utc: str,
    cooldown_minutes: int,
) -> bool:
    since = datetime.fromisoformat(now_utc).replace(tzinfo=UTC) - timedelta(
        minutes=cooldown_minutes
    )
    row = conn.execute(
        "SELECT 1 FROM notifications "
        "WHERE kind = ?1 AND created_at >= ?2 "
        "ORDER BY id DESC LIMIT 1",
        (kind, since.replace(tzinfo=None).isoformat(sep=" ")),
    ).fetchone()
    return row is not None


def _break_recommendation_ignored(conn: sqlite3.Connection, now_utc: str) -> bool:
    value = _runtime_value(conn, "break_ignore_until")
    if value is None:
        return False
    try:
        until = datetime.fromisoformat(value).replace(tzinfo=UTC)
        now = datetime.fromisoformat(now_utc).replace(tzinfo=UTC)
    except ValueError:
        return False
    return now < until


def _active_break_lock(
    db_path: Path,
    now_local: datetime,
    tracking_started_at: datetime | None = None,
) -> dict[str, object] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        _ensure_ml_tables(conn)
        runtime_state = _runtime_value(conn, "break_state")
        planned_until = _runtime_value(conn, "break_planned_until")
        if runtime_state == "BREAK" and planned_until:
            until_utc = _parse_runtime_utc(planned_until)
            if until_utc is not None:
                now_utc = now_local.astimezone(UTC)
                if now_utc < until_utc:
                    remaining = max(int((until_utc - now_utc).total_seconds() // 60), 1)
                    return {
                        "state": "BREAK",
                        "action": f"BREAK_{remaining}",
                        "minutes": remaining,
                        "benefit": 7.0,
                        "until_local": until_utc.astimezone(now_local.tzinfo).strftime("%H:%M"),
                    }
        if tracking_started_at is None:
            row = conn.execute(
                "SELECT timestamp, recommended_action, recommended_duration FROM recommendations "
                "WHERE recommended_action LIKE 'BREAK_%' AND COALESCE(ignored, 0) = 0 "
                "AND COALESCE(accepted, 0) = 0 AND completed_at IS NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT timestamp, recommended_action, recommended_duration FROM recommendations "
                "WHERE recommended_action LIKE 'BREAK_%' AND COALESCE(ignored, 0) = 0 "
                "AND COALESCE(accepted, 0) = 0 AND completed_at IS NULL AND timestamp >= ?1 "
                "ORDER BY id DESC LIMIT 1",
                (tracking_started_at.replace(tzinfo=None).isoformat(sep=" "),),
            ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    created_utc = datetime.fromisoformat(str(row[0])).replace(tzinfo=UTC)
    minutes = int(row[2] or 0)
    if minutes <= 0:
        return None
    until_utc = created_utc + timedelta(minutes=minutes)
    now_utc = now_local.astimezone(UTC)
    if now_utc >= until_utc:
        return None
    action = str(row[1] or f"BREAK_{minutes}")
    return {
        "state": "BREAK_RECOMMENDED",
        "action": action,
        "minutes": minutes,
        "benefit": 7.0,
        "until_local": until_utc.astimezone(now_local.tzinfo).strftime("%H:%M"),
    }


def _parse_runtime_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _active_work_hold(db_path: Path, now_local: datetime) -> dict[str, object] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        _ensure_ml_tables(conn)
        hold_until = _runtime_value(conn, "work_hold_until")
    finally:
        conn.close()
    if hold_until is None:
        return None
    until = _parse_runtime_utc(hold_until)
    if until is None:
        return None
    now_utc = now_local.astimezone(UTC)
    if now_utc >= until:
        return None
    remaining = max(int((until - now_utc).total_seconds() // 60), 1)
    return {
        "remaining_minutes": remaining,
        "until_local": until.astimezone(now_local.tzinfo).strftime("%H:%M"),
    }


def _post_break_work_grace(db_path: Path, now_local: datetime) -> dict[str, object] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        _ensure_ml_tables(conn)
        value = _runtime_value(conn, "last_meaningful_break_at")
    finally:
        conn.close()
    if value is None:
        return None
    break_at = _parse_runtime_utc(value)
    if break_at is None:
        return None
    until = break_at + timedelta(minutes=POST_BREAK_WORK_GRACE_MINUTES)
    now_utc = now_local.astimezone(UTC)
    if now_utc >= until:
        return None
    remaining = max(int((until - now_utc).total_seconds() // 60), 1)
    return {
        "remaining_minutes": remaining,
        "until_local": until.astimezone(now_local.tzinfo).strftime("%H:%M"),
    }


def _should_override_work_hold(
    recommendation: object,
    decline_15m: float,
    decline_60m: float,
) -> bool:
    reason = str(getattr(recommendation, "reason", ""))
    return (
        reason.startswith("conservative_fallback")
        or decline_15m >= 0.74
        or decline_60m >= 0.82
    )


def _tracking_started_at(db_path: Path) -> datetime | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM app_runtime_state WHERE key = 'tracking_started_at'"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return datetime.fromisoformat(str(row[0])).replace(tzinfo=UTC)
    except ValueError:
        return None


def _tracking_elapsed_minutes(started_at: datetime | None, now_local: datetime) -> float | None:
    if started_at is None:
        return None
    return max((now_local.astimezone(UTC) - started_at).total_seconds() / 60, 0.0)


def _show_windows_notification(title: str, body: str) -> None:
    try:
        from attentionos.notifications.windows import WindowsNotifier

        WindowsNotifier().show(title, body)
    except Exception:
        pass


def _warmup(
    reason: str,
    started: float,
    diagnostics: dict[str, object],
    telemetry_minutes: float = 0.0,
) -> dict[str, object]:
    diagnostics["warmup_reason"] = diagnostics.get("warmup_reason") or reason
    return {
        "mode": "demo",
        "status": "warmup",
        "state": "WORK",
        "reason": reason,
        "disclaimer": "Demo model trained on synthetic data.",
        "disclaimer_ru": "Демо-модель обучена на синтетических данных.",
        "current_effectiveness": None,
        "decline_15m": None,
        "decline_30m": None,
        "decline_60m": None,
        "break_benefit": None,
        "recommended_action": "CONTINUE",
        "recommended_break_minutes": None,
        "next_break_eta_minutes": None,
        "policy_source": "WARMUP",
        "active_minutes": telemetry_minutes,
        "telemetry_available_minutes": diagnostics.get(
            "telemetry_available_minutes",
            telemetry_minutes,
        ),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "diagnostics": diagnostics,
    }


def _diagnostics(now_local: datetime, db_path: Path) -> dict[str, object]:
    interval_seconds = _runtime_check_interval_seconds()
    return {
        "model_loaded": False,
        "model_version": None,
        "last_inference_at": now_local.isoformat(),
        "next_inference_at": (now_local + timedelta(seconds=interval_seconds)).isoformat(),
        "telemetry_available_minutes": 0.0,
        "feature_rows_available": 0,
        "feature_vector_valid": False,
        "warmup_reason": None,
        "last_inference_error": None,
        "db_path": str(db_path),
        "local_timezone_offset": now_local.strftime("%z"),
    }


def _telemetry_span_minutes(events: list[dict[str, object]]) -> float:
    if len(events) < 2:
        return 0.0
    first = pd.to_datetime(events[0]["ts_start"])
    last = pd.to_datetime(events[-1].get("ts_end") or events[-1]["ts_start"])
    return max(float((last - first).total_seconds() / 60), 0.0)


def _resolution_minutes(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 1.0
    diffs = df["timestamp"].sort_values().diff().dropna().dt.total_seconds() / 60
    return float(diffs.median()) if not diffs.empty else 1.0


def _effectiveness_to_100(value: float) -> float:
    return float(max(0, min(((value - 1) / 4) * 100, 100)))


def _trend_pressure(row: dict[str, object]) -> float:
    falling_input = 1.0 if float(row.get("input_rate_delta_5_30", 0.0)) < -0.1 else 0.0
    rising_switches = min(max(float(row.get("switch_rate_delta_5_30", 0.0)) * 4, 0), 1)
    rising_idle = min(max(float(row.get("idle_ratio_delta_5_30", 0.0)) * 3, 0), 1)
    long_session = min(max((float(row.get("session_duration_vs_baseline", 1.0)) - 1.2) / 1.5, 0), 1)
    return float(max(0, min((falling_input + rising_switches + rising_idle + long_session) / 4, 1)))


def _signals(row: dict[str, object]) -> list[dict[str, object]]:
    signals = [
        ("Непрерывная работа", "continuous_work_minutes", "мин"),
        ("Переключения 5/30 мин", "switch_rate_delta_5_30", ""),
        ("Активность ввода 5/30 мин", "input_rate_delta_5_30", ""),
        ("Idle trend", "idle_ratio_delta_5_30", ""),
        ("Сессия к baseline", "session_duration_vs_baseline", "x"),
    ]
    return [
        {"label": label, "name": key, "value": round(float(row.get(key, 0.0)), 3), "unit": unit}
        for label, key, unit in signals
    ]


def main() -> None:
    persist = "--no-persist" not in sys.argv
    print(
        json.dumps(
            run_demo_inference(persist=persist),
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()


