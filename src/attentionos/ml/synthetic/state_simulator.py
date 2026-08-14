"""Stateful synthetic telemetry and latent-state simulator."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np

from attentionos.ml.synthetic.user_profiles import SyntheticUserProfile


TASKS = ["coding", "ml", "math", "reading", "writing", "communication", "gaming", "other"]
APPS = {
    "coding": ["Code.exe", "PyCharm.exe", "WindowsTerminal.exe"],
    "ml": ["Code.exe", "Jupyter.exe", "Python.exe"],
    "math": ["Obsidian.exe", "Wolfram.exe"],
    "reading": ["Chrome.exe", "Edge.exe"],
    "writing": ["Word.exe", "Obsidian.exe"],
    "communication": ["Telegram.exe", "Slack.exe", "Teams.exe"],
    "gaming": ["Steam.exe", "Game.exe"],
    "other": ["Explorer.exe", "Chrome.exe"],
}


def simulate_user_day(
    profile: SyntheticUserProfile,
    day_index: int,
    start_date: datetime,
    resolution_seconds: int,
    rng: np.random.Generator,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    day = start_date + timedelta(days=day_index)
    start_hour = float(np.clip(rng.normal(profile.circadian_peak_hour - 3.5, 1.8), 6, 14))
    work_minutes = int(np.clip(rng.normal(430, 90), 180, 720))
    ticks = max(int(work_minutes * 60 / resolution_seconds), 1)
    timestamp = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=start_hour)

    telemetry: list[dict[str, object]] = []
    interventions: list[dict[str, object]] = []
    reports: list[dict[str, object]] = []
    fatigue = float(np.clip(1 - profile.sleep_quality_proxy + rng.normal(0.1, 0.05), 0, 0.7))
    continuous = 0.0
    current_task = str(rng.choice(TASKS[:-1]))
    current_app = str(rng.choice(APPS[current_task]))
    task_elapsed = 0.0
    report_every = max(int(rng.normal(120, 32)), 70)
    next_report_minute = float(rng.integers(35, report_every))

    for tick in range(ticks):
        minute_of_day = timestamp.hour * 60 + timestamp.minute
        hour = minute_of_day / 60
        circadian = _circadian_alignment(hour, profile.circadian_peak_hour)
        should_break = continuous > profile.optimal_session_length and rng.random() < 0.018
        is_idle = rng.random() < (0.02 + fatigue * 0.06) or should_break
        if is_idle:
            break_minutes = float(rng.choice([5, 10, 20], p=[0.45, 0.4, 0.15]))
            fatigue = max(0.0, fatigue - profile.break_recovery_rate * break_minutes / 50)
            continuous = 0.0
            interventions.append(
                {
                    "user_id": profile.user_id,
                    "day": day_index,
                    "timestamp": timestamp,
                    "action": f"BREAK_{int(break_minutes)}",
                    "randomized": True,
                }
            )
        else:
            continuous += resolution_seconds / 60
            task_elapsed += resolution_seconds / 60
            fatigue = min(
                1.0,
                fatigue
                + profile.fatigue_accumulation_rate * (resolution_seconds / 60)
                * (1 + max(continuous - profile.baseline_endurance, 0) / 120),
            )

        switch_prob = 0.025 + max(fatigue - profile.switch_tolerance, 0) * 0.08
        if task_elapsed > rng.normal(55, 24) or rng.random() < switch_prob:
            current_task = str(rng.choice(TASKS, p=[0.22, 0.16, 0.1, 0.12, 0.11, 0.16, 0.04, 0.09]))
            current_app = str(rng.choice(APPS[current_task]))
            task_elapsed = 0.0
        elif rng.random() < switch_prob * 0.65:
            current_app = str(rng.choice(APPS[current_task]))

        difficulty = int(np.clip(round(rng.normal(_task_difficulty(current_task), 0.8)), 1, 5))
        switches_pressure = switch_prob * profile.switch_sensitivity
        effectiveness = float(
            np.clip(
                0.62
                + 0.22 * circadian
                - 0.42 * fatigue
                - 0.12 * max(difficulty - 3, 0)
                - 0.18 * switches_pressure
                - 0.22 * _sigmoid((continuous - profile.baseline_endurance) / 32)
                + rng.normal(0, 0.045),
                0,
                1,
            )
        )
        input_multiplier = max(0.15, 1.15 - fatigue * 0.7 + circadian * 0.18 + rng.normal(0, 0.07))
        keyboard = int(max(0, rng.poisson(profile.baseline_input_rate * input_multiplier)))
        mouse = int(max(0, rng.poisson(profile.baseline_input_rate * 0.55 * input_multiplier)))
        if is_idle:
            keyboard = 0
            mouse = int(rng.poisson(0.3))

        telemetry.append(
            {
                "user_id": profile.user_id,
                "archetype": profile.archetype,
                "day": day_index,
                "timestamp": timestamp,
                "app": current_app,
                "task_category": current_task,
                "difficulty": difficulty,
                "active": 0 if is_idle else 1,
                "idle": 1 if is_idle else 0,
                "keyboard_events": keyboard,
                "mouse_events": mouse,
                "is_distraction": 1 if current_task in {"communication", "gaming"} else 0,
                "latent_effectiveness": effectiveness,
                "latent_fatigue": fatigue,
                "continuous_work_minutes": continuous,
            }
        )
        elapsed_min = tick * resolution_seconds / 60
        if elapsed_min >= next_report_minute:
            reports.append(
                {
                    "user_id": profile.user_id,
                    "day": day_index,
                    "timestamp": timestamp,
                    "effectiveness": _noisy_rating(effectiveness, rng),
                    "fatigue": _noisy_rating(fatigue, rng),
                    "difficulty": difficulty,
                }
            )
            next_report_minute += float(rng.integers(70, 170))

        timestamp += timedelta(seconds=resolution_seconds)
    return telemetry, reports, interventions


def _circadian_alignment(hour: float, peak: float) -> float:
    distance = min(abs(hour - peak), 24 - abs(hour - peak))
    return math.cos(distance / 12 * math.pi)


def _task_difficulty(task: str) -> float:
    return {"math": 4.0, "ml": 4.1, "coding": 3.5, "writing": 3.1, "reading": 2.6, "communication": 2.1, "gaming": 1.8}.get(task, 2.8)


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def _noisy_rating(value: float, rng: np.random.Generator) -> int:
    noisy = np.clip(value + rng.normal(0, 0.13), 0, 1)
    return int(np.clip(round(noisy * 4 + 1), 1, 5))
