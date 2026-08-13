"""Current-state estimation and break recommendation policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StateEstimate:
    """Transparent rule-based state estimate with optional ML risk."""

    focus_score: float
    fatigue_score: float
    fragmentation_score: float
    break_need_score: float
    continuous_work_minutes: float
    time_since_last_break_minutes: float
    switches_15m: int
    ml_low_performance_probability: float = 0.0
    ml_confidence: float = 0.0
    source: str = "baseline"

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "focus_score": self.focus_score,
            "fatigue_score": self.fatigue_score,
            "fragmentation_score": self.fragmentation_score,
            "break_need_score": self.break_need_score,
            "continuous_work_minutes": self.continuous_work_minutes,
            "time_since_last_break_minutes": self.time_since_last_break_minutes,
            "switches_15m": self.switches_15m,
            "ml_low_performance_probability": self.ml_low_performance_probability,
            "ml_confidence": self.ml_confidence,
            "source": self.source,
        }


@dataclass(frozen=True)
class BreakRecommendation:
    """Decision result for a possible break recommendation."""

    should_break: bool
    duration_minutes: int
    confidence: float
    reason: str
    state: StateEstimate


def estimate_state(
    features: dict[str, float | int],
    at_time: datetime,
    ml_probability: float = 0.0,
    ml_confidence: float = 0.0,
) -> StateEstimate:
    """Estimate current state from causal features.

    This is deliberately transparent. If no trained model is available, the
    scores are still meaningful rule-based estimates, not random AI-looking
    numbers.
    """
    continuous = float(features.get("session_age_min", 0.0))
    since_break = float(features.get("time_since_last_break_min", continuous))
    switches = int(features.get("switches_15m", 0))
    uninterrupted = _clamp(float(features.get("uninterrupted_ratio", 0.0)), 0.0, 1.0)
    kb_drop = max(0.0, -float(features.get("kb_rate_change_pct", 0.0))) / 100.0

    fragmentation = _clamp(switches / 35.0, 0.0, 1.0)
    fatigue = _clamp(
        continuous / 120.0 * 0.45
        + since_break / 180.0 * 0.25
        + fragmentation * 0.15
        + kb_drop * 0.15,
        0.0,
        1.0,
    )
    focus = _clamp(uninterrupted * 0.7 + (1.0 - fragmentation) * 0.3, 0.0, 1.0)

    late_day_pressure = 0.08 if at_time.hour >= 16 else 0.0
    break_need = _clamp(
        continuous / 100.0 * 0.45
        + since_break / 150.0 * 0.25
        + fatigue * 0.2
        + ml_probability * ml_confidence * 0.1
        + late_day_pressure,
        0.0,
        1.0,
    )
    return StateEstimate(
        focus_score=focus,
        fatigue_score=fatigue,
        fragmentation_score=fragmentation,
        break_need_score=break_need,
        continuous_work_minutes=continuous,
        time_since_last_break_minutes=since_break,
        switches_15m=switches,
        ml_low_performance_probability=ml_probability,
        ml_confidence=ml_confidence,
        source="hybrid" if ml_confidence > 0 else "baseline",
    )


def recommend_break(
    state: StateEstimate,
    threshold: float = 0.72,
    minimum_work_minutes: int = 45,
) -> BreakRecommendation:
    """Return a rule-based/hybrid break recommendation."""
    should_break = (
        state.break_need_score >= threshold
        and state.continuous_work_minutes >= minimum_work_minutes
    )
    duration = recommended_break_duration(state)
    reason = (
        f"Continuous work: {state.continuous_work_minutes:.0f} min; "
        f"last full break: {state.time_since_last_break_minutes:.0f} min ago."
    )
    return BreakRecommendation(
        should_break=should_break,
        duration_minutes=duration,
        confidence=state.break_need_score,
        reason=reason,
        state=state,
    )


def recommended_break_duration(state: StateEstimate) -> int:
    """Choose a concrete break duration without training a separate model."""
    work = state.continuous_work_minutes
    fatigue = state.fatigue_score
    if work >= 150 or (work >= 120 and fatigue >= 0.75):
        return 25
    if work >= 120:
        return 20
    if work >= 90 and fatigue >= 0.65:
        return 15
    if work >= 70:
        return 10
    return 5


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
