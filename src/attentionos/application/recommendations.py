"""Live recommendation service connecting telemetry, features, model, and storage."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from attentionos.application.state import (
    BreakRecommendation,
    estimate_state,
    recommend_break,
)
from attentionos.config import AppConfig
from attentionos.features.pipeline import FeaturePipeline
from attentionos.settings import RuntimeSettings
from attentionos.storage.db import (
    get_events_range,
    get_recent_interventions,
    insert_intervention,
    insert_notification,
)
from attentionos.storage.schema import (
    Intervention,
    InterventionType,
    Notification,
    ReasonCode,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from attentionos.models.trainer import PersonalStateModel


@dataclass(frozen=True)
class RecommendationResult:
    """Result of one live recommendation evaluation."""

    recommendation: BreakRecommendation
    intervention: Intervention | None = None
    notification: Notification | None = None


class RecommendationService:
    """Periodic live inference service for break recommendations."""

    def __init__(
        self,
        config: AppConfig,
        runtime_settings: RuntimeSettings,
        model: PersonalStateModel | None = None,
    ) -> None:
        self.config = config
        self.runtime_settings = runtime_settings
        self.pipeline = FeaturePipeline()
        self.model = model or self._load_model(config.data_dir / "models" / "personal_state")

    def update_settings(self, settings: RuntimeSettings) -> None:
        """Apply runtime settings without recreating the service."""
        self.runtime_settings = settings

    def evaluate_now(self, at_time: datetime | None = None) -> RecommendationResult | None:
        """Evaluate current telemetry and persist recommendation if needed."""
        if not self.runtime_settings.notifications.break_recommendations:
            return None

        now = _naive_utc(at_time or datetime.now(tz=UTC))
        lookback_start = now - timedelta(hours=6)
        events = list(get_events_range(lookback_start, now, self.config.db_path))
        if not events:
            return None

        features = self.pipeline.compute_features_at(events, now)
        ml_probability = 0.0
        ml_confidence = 0.0
        if self.model is not None and self.model.is_trained:
            ml_probability, ml_confidence = self.model.predict(features)

        state = estimate_state(features, now, ml_probability, ml_confidence)
        recommendation = recommend_break(
            state,
            threshold=self.config.intervention.risk_threshold,
            minimum_work_minutes=45,
        )
        if not recommendation.should_break:
            return RecommendationResult(recommendation=recommendation)
        if not self._cooldown_finished(now):
            return RecommendationResult(recommendation=recommendation)

        intervention = Intervention(
            timestamp=now,
            type=InterventionType.BREAK_10
            if recommendation.duration_minutes <= 10
            else InterventionType.BREAK_20,
            reason_code=ReasonCode.LONG_SESSION,
            pre_state=json.dumps(features, default=str),
            predicted_state=recommendation.state.break_need_score,
            confidence=recommendation.confidence,
            recommended_duration_minutes=recommendation.duration_minutes,
            model_scores=json.dumps(recommendation.state.to_dict(), default=str),
        )
        intervention = insert_intervention(intervention, self.config.db_path)
        notification = insert_notification(
            Notification(
                created_at=now,
                title="Time for a break",
                body=(
                    f"You have been working for "
                    f"{recommendation.state.continuous_work_minutes:.0f} min. "
                    f"Recommended break: {recommendation.duration_minutes} min."
                ),
                intervention_id=intervention.id,
                action_payload=json.dumps(
                    {
                        "duration_minutes": recommendation.duration_minutes,
                        "break_need_score": recommendation.state.break_need_score,
                    }
                ),
            ),
            self.config.db_path,
        )
        return RecommendationResult(
            recommendation=recommendation,
            intervention=intervention,
            notification=notification,
        )

    def _cooldown_finished(self, now: datetime) -> bool:
        recent = get_recent_interventions(limit=1, db_path=self.config.db_path)
        if not recent:
            return True
        latest = recent[0]
        if latest.snoozed_until and latest.snoozed_until > now:
            return False
        cooldown = timedelta(minutes=self.config.intervention.cooldown_minutes)
        return now - latest.timestamp >= cooldown

    @staticmethod
    def _load_model(path: Path) -> PersonalStateModel | None:
        try:
            if (path / "metadata.json").exists():
                from attentionos.models.trainer import PersonalStateModel

                return PersonalStateModel.load(path)
        except Exception:
            logger.exception("Could not load personal state model from %s", path)
        return None


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
