"""Intervention engine — generates recommendations based on ML models and baseline rules."""

from __future__ import annotations

import logging
from datetime import datetime

from attentionos.models.baseline import BaselineRuleEngine
from attentionos.models.trainer import PersonalStateModel
from attentionos.storage.schema import Intervention, InterventionType, ReasonCode

logger = logging.getLogger(__name__)


class InterventionEngine:
    """Evaluates features and generates actionable interventions.

    Uses a combination of:
    1. Baseline Rules (interpretable triggers like "long session without break")
    2. ML Model (predicts low effectiveness probability)

    Includes cooldown logic to prevent spamming the user.
    """

    # Recommendation templates based on the primary trigger
    RECOMMENDATIONS = {
        "long_session": (
            "You've been working continuously for a long time. Take a 5-minute walk."
        ),
        "high_switching": (
            "High context switching detected. Try closing unused tabs and focusing on one task."
        ),
        "short_focus": (
            "Your focus blocks are shorter than usual. Consider enabling 'Do Not Disturb'."
        ),
        "declining_input": (
            "Typing rate dropped. You might be getting tired. Take a quick stretch break."
        ),
        "ml_high_risk": (
            "Our model predicts you are entering a low-performance state. "
            "A 10-minute break is highly recommended now."
        ),
        "default": "Take a moment to breathe and reset.",
    }
    REASON_BY_TRIGGER = {
        "long_session": ReasonCode.LONG_SESSION,
        "high_switching": ReasonCode.SWITCHING,
        "short_focus": ReasonCode.BASELINE_DEVIATION,
        "declining_input": ReasonCode.BASELINE_DEVIATION,
        "ml_high_risk": ReasonCode.BASELINE_DEVIATION,
        "high_idle": ReasonCode.UNUSUAL_IDLE,
    }

    def __init__(
        self,
        baseline_engine: BaselineRuleEngine | None = None,
        ml_model: PersonalStateModel | None = None,
        cooldown_minutes: int = 45,
    ) -> None:
        self.baseline = baseline_engine or BaselineRuleEngine()
        self.ml_model = ml_model
        self.cooldown_sec = cooldown_minutes * 60
        self._last_intervention_time: datetime | None = None

    def evaluate(
        self, features: dict[str, float | int], at_time: datetime
    ) -> Intervention | None:
        """Evaluate current state and optionally generate an intervention.

        Args:
            features: Current feature vector.
            at_time: Current timestamp.

        Returns:
            Intervention object if triggered, else None.
        """
        # Check cooldown
        if (
            self._last_intervention_time is not None
            and (at_time - self._last_intervention_time).total_seconds() < self.cooldown_sec
        ):
            return None

        # 1. Evaluate baseline rules
        alerts = self.baseline.evaluate(features, at_time)
        baseline_risk = self.baseline.get_risk_score(features)

        # 2. Evaluate ML model
        ml_prob = 0.0
        ml_conf = 0.0
        if self.ml_model is not None and self.ml_model.is_trained:
            ml_prob, ml_conf = self.ml_model.predict(features)

        # 3. Decision logic
        trigger = None
        severity = "info"

        # ML model takes precedence if confidence is high and probability > 75%
        if ml_prob > 0.75 and ml_conf > 0.5:
            trigger = "ml_high_risk"
            severity = "high"
        # Otherwise, check baseline alerts
        elif alerts:
            # Sort alerts by severity (high > medium > low)
            severity_rank = {"high": 3, "medium": 2, "low": 1}
            alerts.sort(key=lambda a: severity_rank.get(a.severity, 0), reverse=True)
            top_alert = alerts[0]

            if top_alert.severity in ("high", "medium"):
                trigger = top_alert.rule_name
                severity = top_alert.severity

        # Generate intervention if triggered
        if trigger:
            logger.info("Triggering intervention: %s (severity: %s)", trigger, severity)
            self._last_intervention_time = at_time

            return Intervention(
                timestamp=at_time,
                type=InterventionType.BREAK,
                reason_code=self.REASON_BY_TRIGGER.get(trigger),
                predicted_state=max(ml_prob, baseline_risk),
                confidence=ml_conf if ml_prob > 0 else min(max(baseline_risk, 0.0), 1.0),
                accepted=False,
            )

        return None
