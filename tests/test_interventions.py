"""Tests for intervention generation."""

from __future__ import annotations

from datetime import UTC, datetime

from attentionos.interventions.engine import InterventionEngine
from attentionos.storage.schema import InterventionType, ReasonCode


class FakeModel:
    is_trained = True

    @staticmethod
    def predict(_features: dict[str, float | int]) -> tuple[float, float]:
        return 0.9, 0.8


def test_ml_intervention_matches_schema() -> None:
    engine = InterventionEngine(ml_model=FakeModel())
    intervention = engine.evaluate({}, datetime(2026, 8, 10, 12, 0, tzinfo=UTC))

    assert intervention is not None
    assert intervention.type == InterventionType.BREAK
    assert intervention.reason_code == ReasonCode.BASELINE_DEVIATION
    assert intervention.predicted_state == 0.9
    assert intervention.confidence == 0.8
    assert intervention.accepted is False
