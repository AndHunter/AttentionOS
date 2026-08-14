"""Demo recommendation policy using model outputs plus safety rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Action = Literal["CONTINUE", "BREAK_10", "BREAK_20", "SWITCH_TASK"]


@dataclass(frozen=True)
class DemoRecommendation:
    action: Action
    title: str
    reason: str
    confidence: float


def recommend_action(
    current_effectiveness: float,
    decline_probability: float,
    break_benefit: float,
    continuous_work_minutes: float,
    time_since_last_break: float,
    workload_last_4h: float,
) -> DemoRecommendation:
    """Return a transparent demo recommendation without medical claims."""
    if workload_last_4h >= 210 and break_benefit >= 0.55:
        return DemoRecommendation(
            "BREAK_20",
            "Break recommended",
            "High accumulated workload and demo break-benefit score.",
            max(decline_probability, break_benefit),
        )
    if decline_probability >= 0.68 and break_benefit >= 0.45:
        return DemoRecommendation(
            "BREAK_10",
            "Break recommended",
            "Demo model expects possible effectiveness decline; a short break has positive expected benefit.",
            max(decline_probability, break_benefit),
        )
    if continuous_work_minutes >= 110 and decline_probability >= 0.42:
        return DemoRecommendation(
            "BREAK_10",
            "Short break suggested",
            "Current session is longer than usual and decline risk is moderate.",
            decline_probability,
        )
    if current_effectiveness <= 2.4 and decline_probability >= 0.55 and time_since_last_break < 35:
        return DemoRecommendation(
            "SWITCH_TASK",
            "Switch task suggested",
            "Demo model sees lower current effectiveness shortly after a break.",
            decline_probability,
        )
    return DemoRecommendation(
        "CONTINUE",
        "Continue",
        "Decline risk is low or break benefit is not high enough.",
        1.0 - decline_probability,
    )

