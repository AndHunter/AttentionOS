"""Production-like rolling features used by synthetic training and demo inference."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


WINDOWS = (1, 5, 15, 30, 60, 120)
CATEGORICAL_FEATURES = ["task_category"]


@dataclass(frozen=True)
class FeatureSchema:
    numeric: list[str]
    categorical: list[str]

    @property
    def all(self) -> list[str]:
        return self.numeric + self.categorical


def feature_schema() -> FeatureSchema:
    numeric = [
        "hour",
        "minute",
        "time_of_day_sin",
        "time_of_day_cos",
        "minutes_since_wake_proxy",
        "continuous_work_minutes",
        "time_since_last_break",
        "current_session_duration",
        "active_time_today",
        "focus_time_today",
        "workload_last_2h",
        "workload_last_4h",
        "work_episode_elapsed_minutes",
        "active_time_since_work_start",
        "idle_time_since_work_start",
        "switches_since_work_start",
        "input_events_since_work_start",
        "focus_blocks_since_work_start",
        "breaks_since_work_start",
        "break_count_today",
        "total_break_time_today",
        "last_break_duration",
        "current_app_duration",
        "task_duration",
        "task_switches_today",
        "difficulty",
        "input_rate_delta_1_15",
        "input_rate_delta_5_30",
        "keyboard_rate_delta_5_30",
        "mouse_rate_delta_5_30",
        "switch_rate_delta_5_30",
        "switch_rate_delta_15_60",
        "active_ratio_delta_5_30",
        "idle_ratio_delta_5_30",
        "app_entropy_delta_5_30",
        "input_rate_slope_15m",
        "input_rate_slope_30m",
        "switch_rate_slope_30m",
        "active_ratio_slope_30m",
        "switch_rate_vs_baseline",
        "input_rate_vs_baseline",
        "session_duration_vs_baseline",
        "active_ratio_vs_baseline",
    ]
    for window in WINDOWS:
        numeric.extend(
            [
                f"active_ratio_{window}m",
                f"idle_ratio_{window}m",
                f"switch_count_{window}m",
                f"switch_rate_{window}m",
                f"keyboard_rate_{window}m",
                f"mouse_rate_{window}m",
                f"unique_apps_{window}m",
            ]
        )
    numeric.extend(["app_entropy_5m", "app_entropy_15m", "app_entropy_30m", "app_entropy_60m", "app_entropy_120m"])
    return FeatureSchema(numeric=numeric, categorical=CATEGORICAL_FEATURES.copy())


def build_training_windows(telemetry: pd.DataFrame, step_minutes: int = 5) -> pd.DataFrame:
    """Build causal rolling features for each synthetic user/day."""
    if telemetry.empty:
        return pd.DataFrame(columns=feature_schema().all)
    telemetry = telemetry.sort_values(["user_id", "timestamp"]).copy()
    telemetry["timestamp"] = pd.to_datetime(telemetry["timestamp"])
    rows: list[dict[str, object]] = []
    for (_user, day), group in telemetry.groupby(["user_id", "day"], sort=False):
        group = group.reset_index(drop=True)
        start = group["timestamp"].min() + timedelta(minutes=30)
        end = group["timestamp"].max()
        current = start
        while current <= end:
            rows.append(build_features_at(group, current))
            current += timedelta(minutes=step_minutes)
    return pd.DataFrame(rows)


def build_features_at(events: pd.DataFrame, at_time: datetime | pd.Timestamp) -> dict[str, object]:
    """Build one production-like feature row using only events at or before at_time."""
    at = pd.Timestamp(at_time).to_pydatetime()
    causal = events[pd.to_datetime(events["timestamp"]) <= at].copy()
    if causal.empty:
        return _neutral_row(at)
    causal["timestamp"] = pd.to_datetime(causal["timestamp"])
    day_start = causal["timestamp"].dt.normalize().iloc[-1]
    latest = causal.iloc[-1]
    row = _neutral_row(at)
    row.update(
        {
            "user_id": latest.get("user_id", "real"),
            "day": latest.get("day", at.date().isoformat()),
            "timestamp": at,
            "task_category": str(latest.get("task_category", "other")),
            "difficulty": float(latest.get("difficulty", 3.0)),
        }
    )

    elapsed = max((at - day_start.to_pydatetime()).total_seconds() / 60.0, 1.0)
    row["active_time_today"] = float(causal["active"].sum() * _resolution_minutes(causal))
    row["focus_time_today"] = float(
        causal[(causal["active"] > 0) & (causal["is_distraction"] == 0)]["active"].sum()
        * _resolution_minutes(causal)
    )
    row["workload_last_2h"] = _active_minutes(causal, at, 120)
    row["workload_last_4h"] = _active_minutes(causal, at, 240)
    row["current_session_duration"] = _current_session_minutes(causal)
    row["current_app_duration"] = row["current_session_duration"]
    row["continuous_work_minutes"] = _continuous_work_minutes(causal)
    row["time_since_last_break"] = _time_since_last_break(causal)
    row["work_episode_elapsed_minutes"] = row["time_since_last_break"]
    row["active_time_since_work_start"] = _active_since_current_work_start(causal)
    row["idle_time_since_work_start"] = _idle_since_current_work_start(causal)
    row["switches_since_work_start"] = _switches_since_current_work_start(causal)
    row["input_events_since_work_start"] = _input_since_current_work_start(causal)
    row["focus_blocks_since_work_start"] = 1 if row["continuous_work_minutes"] >= 25 else 0
    row["breaks_since_work_start"] = 0
    breaks = _break_durations(causal)
    row["break_count_today"] = len(breaks)
    row["total_break_time_today"] = float(sum(breaks))
    row["last_break_duration"] = float(breaks[-1]) if breaks else 0.0
    row["task_duration"] = _current_task_minutes(causal, str(latest.get("task_category", "other")))
    row["task_switches_today"] = int((causal["task_category"] != causal["task_category"].shift()).sum() - 1)
    row["minutes_since_wake_proxy"] = elapsed

    for window in WINDOWS:
        window_df = _window(causal, at, window)
        _add_window(row, window_df, window)

    row["input_rate_delta_1_15"] = (row["keyboard_rate_1m"] + row["mouse_rate_1m"]) - (
        row["keyboard_rate_15m"] + row["mouse_rate_15m"]
    )
    row["input_rate_delta_5_30"] = (row["keyboard_rate_5m"] + row["mouse_rate_5m"]) - (
        row["keyboard_rate_30m"] + row["mouse_rate_30m"]
    )
    row["keyboard_rate_delta_5_30"] = row["keyboard_rate_5m"] - row["keyboard_rate_30m"]
    row["mouse_rate_delta_5_30"] = row["mouse_rate_5m"] - row["mouse_rate_30m"]
    row["switch_rate_delta_5_30"] = row["switch_rate_5m"] - row["switch_rate_30m"]
    row["switch_rate_delta_15_60"] = row["switch_rate_15m"] - row["switch_rate_60m"]
    row["active_ratio_delta_5_30"] = row["active_ratio_5m"] - row["active_ratio_30m"]
    row["idle_ratio_delta_5_30"] = row["idle_ratio_5m"] - row["idle_ratio_30m"]
    row["app_entropy_delta_5_30"] = row["app_entropy_5m"] - row["app_entropy_30m"]
    row["input_rate_slope_15m"] = _slope_rates(causal, at, 15, "input")
    row["input_rate_slope_30m"] = _slope_rates(causal, at, 30, "input")
    row["switch_rate_slope_30m"] = _slope_rates(causal, at, 30, "switch")
    row["active_ratio_slope_30m"] = _slope_rates(causal, at, 30, "active")

    baseline = _baseline(causal)
    input_rate = row["keyboard_rate_30m"] + row["mouse_rate_30m"]
    row["switch_rate_vs_baseline"] = _ratio(row["switch_rate_30m"], baseline["switch_rate"])
    row["input_rate_vs_baseline"] = _ratio(input_rate, baseline["input_rate"])
    row["session_duration_vs_baseline"] = _ratio(row["current_session_duration"], baseline["session"])
    row["active_ratio_vs_baseline"] = _ratio(row["active_ratio_30m"], baseline["active_ratio"])
    return row


def real_events_to_frame(events: list[dict[str, object]]) -> pd.DataFrame:
    """Convert SQLite activity rows to the feature-builder event shape."""
    rows = []
    for event in events:
        ts = _to_local_timestamp(event["ts_start"])
        process = str(event.get("process_name") or "unknown").lower()
        task = str(event.get("task_label") or "other").lower()
        rows.append(
            {
                "user_id": "real",
                "day": ts.date().isoformat(),
                "timestamp": ts,
                "app": process,
                "task_category": _task_category(task),
                "difficulty": 3.0,
                "active": 1 if float(event.get("idle_seconds") or 0) < 120 else 0,
                "idle": 1 if float(event.get("idle_seconds") or 0) >= 120 else 0,
                "keyboard_events": int(event.get("keyboard_events") or 0),
                "mouse_events": int(event.get("mouse_events") or 0),
                "is_distraction": 1 if _task_category(task) in {"gaming", "rest"} else 0,
            }
        )
    return pd.DataFrame(rows)


def _to_local_timestamp(value: object) -> pd.Timestamp:
    """Treat stored naive SQLite timestamps as UTC and expose local computer time."""
    ts = pd.to_datetime(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    local_tz = datetime.now().astimezone().tzinfo
    return ts.tz_convert(local_tz).tz_localize(None)


def load_dataset(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def _neutral_row(at: datetime) -> dict[str, object]:
    hour_float = at.hour + at.minute / 60.0
    row: dict[str, object] = {
        "user_id": "unknown",
        "day": at.date().isoformat(),
        "timestamp": at,
        "hour": at.hour,
        "minute": at.minute,
        "time_of_day_sin": math.sin(2 * math.pi * hour_float / 24),
        "time_of_day_cos": math.cos(2 * math.pi * hour_float / 24),
        "task_category": "other",
        "difficulty": 3.0,
    }
    for name in feature_schema().numeric:
        row.setdefault(name, 0.0)
    return row


def _resolution_minutes(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 1.0
    diffs = df["timestamp"].sort_values().diff().dropna().dt.total_seconds() / 60.0
    return float(diffs.median()) if not diffs.empty else 1.0


def _window(df: pd.DataFrame, at: datetime, minutes: int) -> pd.DataFrame:
    return df[df["timestamp"] >= pd.Timestamp(at - timedelta(minutes=minutes))]


def _add_window(row: dict[str, object], df: pd.DataFrame, minutes: int) -> None:
    denom = max(minutes, 1)
    if df.empty:
        for key in ["active_ratio", "idle_ratio", "switch_count", "switch_rate", "keyboard_rate", "mouse_rate", "unique_apps"]:
            row[f"{key}_{minutes}m"] = 0.0
        if minutes in (5, 15, 30, 60, 120):
            row[f"app_entropy_{minutes}m"] = 0.0
        return
    row[f"active_ratio_{minutes}m"] = float(df["active"].mean())
    row[f"idle_ratio_{minutes}m"] = float(df["idle"].mean())
    switches = int((df["app"] != df["app"].shift()).sum() - 1)
    row[f"switch_count_{minutes}m"] = max(switches, 0)
    row[f"switch_rate_{minutes}m"] = max(switches, 0) / denom
    row[f"keyboard_rate_{minutes}m"] = float(df["keyboard_events"].sum()) / denom
    row[f"mouse_rate_{minutes}m"] = float(df["mouse_events"].sum()) / denom
    row[f"unique_apps_{minutes}m"] = int(df["app"].nunique())
    if minutes in (5, 15, 30, 60, 120):
        counts = df["app"].value_counts(normalize=True)
        row[f"app_entropy_{minutes}m"] = float(-(counts * np.log2(counts + 1e-9)).sum())


def _active_minutes(df: pd.DataFrame, at: datetime, minutes: int) -> float:
    w = _window(df, at, minutes)
    return float(w["active"].sum() * _resolution_minutes(df))


def _current_session_minutes(df: pd.DataFrame) -> float:
    latest_app = df.iloc[-1]["app"]
    rev = df.iloc[::-1]
    count = 0
    for _, row in rev.iterrows():
        if row["app"] != latest_app or row["idle"] > 0 or _is_rest_task(row):
            break
        count += 1
    return count * _resolution_minutes(df)


def _continuous_work_minutes(df: pd.DataFrame) -> float:
    rev = df.iloc[::-1]
    count = 0
    for _, row in rev.iterrows():
        if row["idle"] > 0 or _is_rest_task(row):
            break
        count += 1
    return count * _resolution_minutes(df)


def _time_since_last_break(df: pd.DataFrame) -> float:
    rev = df.iloc[::-1]
    count = 0
    for _, row in rev.iterrows():
        if row["idle"] > 0 or _is_rest_task(row):
            break
        count += 1
    return count * _resolution_minutes(df)


def _current_work_episode(df: pd.DataFrame, min_break_minutes: float = 5.0) -> pd.DataFrame:
    if df.empty:
        return df
    res = _resolution_minutes(df)
    idle_run = 0.0
    cutoff_index = -1
    for idx in range(len(df) - 1, -1, -1):
        row = df.iloc[idx]
        if row["idle"] > 0 or _is_rest_task(row):
            idle_run += res
            if idle_run >= min_break_minutes:
                cutoff_index = idx
                break
        else:
            idle_run = 0.0
    if cutoff_index < 0:
        return df
    return df.iloc[cutoff_index + 1 :].copy()


def _break_durations(df: pd.DataFrame, min_break_minutes: float = 5.0) -> list[float]:
    if df.empty:
        return []
    res = _resolution_minutes(df)
    breaks: list[float] = []
    current = 0.0
    for _, row in df.iterrows():
        is_break = row["idle"] > 0 or _is_rest_task(row)
        if is_break:
            current += res
            continue
        if current >= min_break_minutes:
            breaks.append(current)
        current = 0.0
    if current >= min_break_minutes:
        breaks.append(current)
    return breaks


def _is_rest_task(row: pd.Series) -> bool:
    return str(row.get("task_category", "")).lower() in {"rest", "отдых"}


def _active_since_current_work_start(df: pd.DataFrame) -> float:
    episode = _current_work_episode(df)
    return float(episode["active"].sum() * _resolution_minutes(df)) if not episode.empty else 0.0


def _idle_since_current_work_start(df: pd.DataFrame) -> float:
    episode = _current_work_episode(df)
    return float(episode["idle"].sum() * _resolution_minutes(df)) if not episode.empty else 0.0


def _switches_since_current_work_start(df: pd.DataFrame) -> int:
    episode = _current_work_episode(df)
    if episode.empty:
        return 0
    return int(max((episode["app"] != episode["app"].shift()).sum() - 1, 0))


def _input_since_current_work_start(df: pd.DataFrame) -> int:
    episode = _current_work_episode(df)
    if episode.empty:
        return 0
    return int(episode["keyboard_events"].sum() + episode["mouse_events"].sum())


def _current_task_minutes(df: pd.DataFrame, task: str) -> float:
    rev = df.iloc[::-1]
    count = 0
    for _, row in rev.iterrows():
        if row["task_category"] != task:
            break
        count += 1
    return count * _resolution_minutes(df)


def _slope_rates(df: pd.DataFrame, at: datetime, minutes: int, kind: str) -> float:
    w = _window(df, at, minutes)
    if len(w) < 4:
        return 0.0
    chunks = [w.loc[indexes] for indexes in np.array_split(w.index.to_numpy(), 4)]
    values = []
    for chunk in chunks:
        if kind == "input":
            values.append(float(chunk["keyboard_events"].sum() + chunk["mouse_events"].sum()))
        elif kind == "switch":
            values.append(float((chunk["app"] != chunk["app"].shift()).sum() - 1))
        else:
            values.append(float(chunk["active"].mean()))
    return float(np.polyfit(range(len(values)), values, 1)[0])


def _baseline(df: pd.DataFrame) -> dict[str, float]:
    recent = df.tail(min(len(df), 240))
    return {
        "switch_rate": float(max((recent["app"] != recent["app"].shift()).sum() - 1, 0) / max(len(recent), 1)),
        "input_rate": float((recent["keyboard_events"].median() + recent["mouse_events"].median())),
        "session": max(_current_session_minutes(recent), 1.0),
        "active_ratio": float(max(recent["active"].median(), 0.01)),
    }


def _ratio(value: object, baseline: float) -> float:
    return float(value) / max(float(baseline), 1e-6)


def _task_category(task: str) -> str:
    task = task.lower()
    if task in {"work", "работа"}:
        return "work"
    if task in {"coding", "code", "программирование"}:
        return "coding"
    if task in {"rest", "отдых"}:
        return "rest"
    if task in {"gaming", "game", "игра"}:
        return "gaming"
    if task in {"reading", "чтение"}:
        return "reading"
    if task in {"writing", "письмо"}:
        return "writing"
    if task in {"communication", "общение"}:
        return "communication"
    if task in {"other", "другое", "none"}:
        return "other"
    if "ml" in task:
        return "ml"
    if "math" in task:
        return "math"
    if "english" in task or "англий" in task:
        return "english"
    if "read" in task or "чтен" in task:
        return "reading"
    if "meeting" in task or "telegram" in task:
        return "communication"
    if "code" in task or "coding" in task:
        return "coding"
    return "other"
