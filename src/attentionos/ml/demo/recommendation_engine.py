"""Demo recommendation policy using model outputs plus explicit safety rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RecommendationState = Literal["WORK", "BREAK_RECOMMENDED", "BREAK", "READY_TO_WORK"]
Action = Literal["CONTINUE", "BREAK_5", "BREAK_10", "BREAK_15", "BREAK_20", "BREAK_30", "SWITCH_TASK"]

MEANINGFUL_BREAK_MINUTES = 5
MAX_CONTINUOUS_WORK_MINUTES = 120
SOFT_CONTINUOUS_WORK_MINUTES = 75
BREAK_CANDIDATES = (5, 10, 15, 20, 30)


@dataclass(frozen=True)
class DemoRecommendation:
    action: Action
    state: RecommendationState
    title: str
    reason: str
    confidence: float
    recommended_break_minutes: int | None
    break_benefit: float
    next_break_eta_minutes: int | None
    policy_source: Literal["MODEL", "FALLBACK", "WARMUP"]
    continue_utility: float
    best_break_utility: float
    utilities: dict[str, float]


def recommend_action(
    current_effectiveness: float,
    decline_15m: float,
    decline_30m: float,
    decline_60m: float,
    raw_break_benefit: float,
    continuous_work_minutes: float,
    time_since_last_break: float,
    workload_last_4h: float,
    input_rate_delta_5_30: float = 0.0,
    switch_rate_delta_5_30: float = 0.0,
    idle_ratio_delta_5_30: float = 0.0,
    session_duration_vs_baseline: float = 1.0,
    break_count_today: float = 0.0,
    last_break_duration: float = 0.0,
    active_ratio_15m: float = 1.0,
    idle_ratio_15m: float = 0.0,
) -> DemoRecommendation:
    """Choose WORK/BREAK using current model estimates and conservative guardrails."""
    effectiveness_100 = _effectiveness_to_100(current_effectiveness)
    trend_pressure = _trend_pressure(
        input_rate_delta_5_30=input_rate_delta_5_30,
        switch_rate_delta_5_30=switch_rate_delta_5_30,
        idle_ratio_delta_5_30=idle_ratio_delta_5_30,
        session_duration_vs_baseline=session_duration_vs_baseline,
    )
    first_break_pressure = 1.0 if break_count_today <= 0 and continuous_work_minutes >= 60 else 0.0
    rest_debt = min(max((time_since_last_break - 50) / 90, 0), 1)
    weak_recent_activity = 1.0 if continuous_work_minutes >= 45 and active_ratio_15m < 0.55 else 0.0
    incomplete_recovery = 1.0 if 0 < last_break_duration < MEANINGFUL_BREAK_MINUTES else 0.0
    continue_utility = (
        effectiveness_100
        - decline_60m * 34
        - max(continuous_work_minutes - 60, 0) * 0.07
        - trend_pressure * 8
        - first_break_pressure * 6
        - rest_debt * 6
        - weak_recent_activity * 5
        - incomplete_recovery * 5
    )
    utilities: dict[str, float] = {"CONTINUE": round(continue_utility, 3)}
    fatigue_pressure = min(max(continuous_work_minutes / 150, 0), 1.4)
    for minutes in BREAK_CANDIDATES:
        recovery = (
            (raw_break_benefit * 24)
            + (decline_60m * 13)
            + (fatigue_pressure * 10)
            + (first_break_pressure * 6)
            + (rest_debt * 8)
            + (weak_recent_activity * 5)
            + (incomplete_recovery * 5)
            + max(idle_ratio_15m - 0.18, 0) * 8
        )
        duration_fit = 8 - abs(minutes - _preferred_break_minutes(continuous_work_minutes, decline_60m)) * 0.35
        excessive_break_penalty = max(minutes - 20, 0) * 0.32
        utilities[f"BREAK_{minutes}"] = round(effectiveness_100 + recovery + duration_fit - excessive_break_penalty, 3)
    utilities["SWITCH_TASK"] = round(effectiveness_100 - decline_30m * 12 + trend_pressure * 6, 3)

    best_break_action = max((f"BREAK_{m}" for m in BREAK_CANDIDATES), key=lambda key: utilities[key])
    best_break_utility = utilities[best_break_action]
    model_best_action = max(utilities, key=utilities.get)
    model_break_benefit = _benefit_0_10(best_break_utility - continue_utility)
    next_eta = _next_break_eta(decline_15m, decline_30m, decline_60m)

    if continuous_work_minutes >= MAX_CONTINUOUS_WORK_MINUTES and time_since_last_break >= MEANINGFUL_BREAK_MINUTES:
        minutes = max(10, int(best_break_action.split("_")[1]))
        return DemoRecommendation(
            action=f"BREAK_{minutes}",  # type: ignore[return-value]
            state="BREAK_RECOMMENDED",
            title="Break recommended",
            reason="conservative_fallback: continuous work exceeded the demo safety limit without a meaningful break.",
            confidence=max(0.78, decline_60m, raw_break_benefit),
            recommended_break_minutes=minutes,
            break_benefit=max(model_break_benefit, 7.0),
            next_break_eta_minutes=0,
            policy_source="FALLBACK",
            continue_utility=round(continue_utility, 3),
            best_break_utility=round(best_break_utility, 3),
            utilities=utilities,
        )

    if (
        continuous_work_minutes >= SOFT_CONTINUOUS_WORK_MINUTES
        and (trend_pressure >= 0.55 or decline_30m >= 0.54 or model_break_benefit >= 5.8)
    ):
        minutes = int(best_break_action.split("_")[1])
        return _break_result(
            best_break_action,
            minutes,
            "Soft break suggested",
            "continuous work is elevated and recent behavioral trend is weakening.",
            max(decline_30m, raw_break_benefit, 0.62),
            max(model_break_benefit, 5.5),
            continue_utility,
            best_break_utility,
            utilities,
            "MODEL",
        )

    if (
        continuous_work_minutes >= 60
        and first_break_pressure > 0
        and (decline_30m >= 0.42 or model_break_benefit >= 5.2 or trend_pressure >= 0.35 or weak_recent_activity > 0)
    ):
        minutes = int(best_break_action.split("_")[1])
        return _break_result(
            best_break_action,
            minutes,
            "First break suggested",
            "first_break_guard: no meaningful break has been observed today and fatigue signals are rising.",
            max(decline_30m, raw_break_benefit, 0.58),
            max(model_break_benefit, 5.2),
            continue_utility,
            best_break_utility,
            utilities,
            "MODEL",
        )

    if (
        continuous_work_minutes >= 45
        and model_break_benefit >= 7.0
        and best_break_utility - continue_utility >= 18
        and (
            decline_30m >= 0.45
            or trend_pressure >= 0.35
            or switch_rate_delta_5_30 >= 0.45
            or input_rate_delta_5_30 <= -0.2
            or weak_recent_activity > 0
        )
    ):
        minutes = int(best_break_action.split("_")[1])
        return _break_result(
            best_break_action,
            minutes,
            "Break recommended",
            "action_utility: modeled break utility is substantially higher than continuing.",
            max(decline_30m, raw_break_benefit, 0.68),
            model_break_benefit,
            continue_utility,
            best_break_utility,
            utilities,
            "MODEL",
        )

    if model_best_action.startswith("BREAK") and model_break_benefit >= 4.8 and decline_30m >= 0.45:
        minutes = int(model_best_action.split("_")[1])
        return _break_result(
            model_best_action,
            minutes,
            "Break recommended",
            "demo model expects better future output after a short recovery period.",
            max(decline_30m, raw_break_benefit),
            model_break_benefit,
            continue_utility,
            best_break_utility,
            utilities,
            "MODEL",
        )

    if model_best_action == "SWITCH_TASK" and decline_30m >= 0.55:
        return DemoRecommendation(
            "SWITCH_TASK",
            "WORK",
            "Switch task suggested",
            "current pattern looks inefficient, but a break is not the best modeled action yet.",
            decline_30m,
            None,
            model_break_benefit,
            next_eta,
            "MODEL",
            round(continue_utility, 3),
            round(best_break_utility, 3),
            utilities,
        )

    display_break_benefit = model_break_benefit
    if decline_30m < 0.45 and trend_pressure < 0.35 and weak_recent_activity == 0:
        display_break_benefit = min(display_break_benefit, 4.9)

    return DemoRecommendation(
        "CONTINUE",
        "WORK",
        "Continue working",
        "decline risk is not high enough and break utility does not beat continuing.",
        max(0.0, 1.0 - decline_30m),
        None,
        display_break_benefit,
        next_eta,
        "MODEL",
        round(continue_utility, 3),
        round(best_break_utility, 3),
        utilities,
    )


def _break_result(
    action: str,
    minutes: int,
    title: str,
    reason: str,
    confidence: float,
    break_benefit: float,
    continue_utility: float,
    best_break_utility: float,
    utilities: dict[str, float],
    policy_source: Literal["MODEL", "FALLBACK"],
) -> DemoRecommendation:
    return DemoRecommendation(
        action=action,  # type: ignore[arg-type]
        state="BREAK_RECOMMENDED",
        title=title,
        reason=reason,
        confidence=confidence,
        recommended_break_minutes=minutes,
        break_benefit=break_benefit,
        next_break_eta_minutes=0,
        policy_source=policy_source,
        continue_utility=round(continue_utility, 3),
        best_break_utility=round(best_break_utility, 3),
        utilities=utilities,
    )


def _effectiveness_to_100(value: float) -> float:
    if value > 5:
        return float(max(0, min(value, 100)))
    return float(max(0, min(((value - 1) / 4) * 100, 100)))


def _benefit_0_10(utility_delta: float) -> float:
    return round(float(max(0, min(utility_delta / 5.0, 10))), 1)


def _preferred_break_minutes(continuous_work_minutes: float, decline_60m: float) -> int:
    if continuous_work_minutes >= 150 or decline_60m >= 0.75:
        return 20
    if continuous_work_minutes >= 100 or decline_60m >= 0.62:
        return 15
    if continuous_work_minutes >= 70 or decline_60m >= 0.48:
        return 10
    return 5


def _next_break_eta(decline_15m: float, decline_30m: float, decline_60m: float) -> int | None:
    if decline_15m >= 0.68:
        return 0
    if decline_30m >= 0.58:
        return 15
    if decline_60m >= 0.55:
        return 30
    return 5


def _trend_pressure(
    input_rate_delta_5_30: float,
    switch_rate_delta_5_30: float,
    idle_ratio_delta_5_30: float,
    session_duration_vs_baseline: float,
) -> float:
    falling_input = 1.0 if input_rate_delta_5_30 < -0.1 else 0.0
    rising_switches = min(max(switch_rate_delta_5_30 * 4, 0), 1)
    rising_idle = min(max(idle_ratio_delta_5_30 * 3, 0), 1)
    long_session = min(max((session_duration_vs_baseline - 1.2) / 1.5, 0), 1)
    return float(max(0, min((falling_input + rising_switches + rising_idle + long_session) / 4, 1)))
