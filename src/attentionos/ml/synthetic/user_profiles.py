"""Synthetic user profiles with hidden individual parameters."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


ARCHETYPES = [
    "high_endurance",
    "low_endurance",
    "morning_type",
    "evening_type",
    "high_switch_tolerance",
    "low_switch_tolerance",
    "frequent_break_worker",
    "long_deep_work_worker",
    "high_input_activity",
    "low_input_activity",
]


@dataclass(frozen=True)
class SyntheticUserProfile:
    user_id: str
    archetype: str
    baseline_endurance: float
    optimal_session_length: float
    circadian_peak_hour: float
    switch_sensitivity: float
    fatigue_accumulation_rate: float
    break_recovery_rate: float
    task_difficulty_sensitivity: float
    sleep_quality_proxy: float
    baseline_input_rate: float
    switch_tolerance: float
    break_preference_minutes: float


def sample_profiles(users: int, seed: int) -> list[SyntheticUserProfile]:
    rng = np.random.default_rng(seed)
    profiles: list[SyntheticUserProfile] = []
    for index in range(users):
        archetype = str(rng.choice(ARCHETYPES))
        endurance = float(rng.normal(95, 24))
        session = float(rng.normal(75, 22))
        peak = float(rng.normal(14, 3.5))
        switch_sensitivity = float(rng.lognormal(-0.2, 0.35))
        fatigue_rate = float(rng.lognormal(-2.8, 0.35))
        recovery = float(rng.uniform(0.45, 0.9))
        input_rate = float(rng.normal(18, 5))
        switch_tolerance = float(rng.normal(0.55, 0.15))
        break_pref = float(rng.normal(12, 5))

        if archetype == "high_endurance":
            endurance += 45
            session += 25
            fatigue_rate *= 0.72
        elif archetype == "low_endurance":
            endurance -= 35
            session -= 15
            fatigue_rate *= 1.35
        elif archetype == "morning_type":
            peak = float(rng.normal(9.5, 1.2))
        elif archetype == "evening_type":
            peak = float(rng.normal(18.5, 1.5))
        elif archetype == "high_switch_tolerance":
            switch_tolerance += 0.35
            switch_sensitivity *= 0.55
        elif archetype == "low_switch_tolerance":
            switch_tolerance -= 0.25
            switch_sensitivity *= 1.55
        elif archetype == "frequent_break_worker":
            break_pref -= 5
            recovery *= 1.18
        elif archetype == "long_deep_work_worker":
            session += 45
            break_pref += 8
        elif archetype == "high_input_activity":
            input_rate += 10
        elif archetype == "low_input_activity":
            input_rate -= 7

        profiles.append(
            SyntheticUserProfile(
                user_id=f"synthetic-{index:05d}",
                archetype=archetype,
                baseline_endurance=max(endurance, 35),
                optimal_session_length=max(session, 25),
                circadian_peak_hour=peak % 24,
                switch_sensitivity=max(switch_sensitivity, 0.1),
                fatigue_accumulation_rate=max(fatigue_rate, 0.005),
                break_recovery_rate=min(max(recovery, 0.2), 1.2),
                task_difficulty_sensitivity=float(rng.uniform(0.05, 0.18)),
                sleep_quality_proxy=float(rng.beta(7, 3)),
                baseline_input_rate=max(input_rate, 3),
                switch_tolerance=min(max(switch_tolerance, 0.05), 1.2),
                break_preference_minutes=max(break_pref, 4),
            )
        )
    return profiles

