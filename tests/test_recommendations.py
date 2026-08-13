from __future__ import annotations

from datetime import UTC, datetime, timedelta

from attentionos.application.recommendations import RecommendationService
from attentionos.application.state import StateEstimate, recommend_break, recommended_break_duration
from attentionos.config import AppConfig, CollectorConfig, InterventionConfig
from attentionos.notifications.service import NotificationService
from attentionos.settings import RuntimeSettings
from attentionos.storage.db import (
    count_unread_notifications,
    get_notifications,
    get_recent_interventions,
    init_db,
    insert_event,
    reset_engine,
)
from attentionos.storage.schema import ActivityEvent, InterventionResponse, NotificationState


def _event(ts: datetime, process: str = "Code.exe") -> ActivityEvent:
    return ActivityEvent(
        ts_start=ts,
        ts_end=ts + timedelta(seconds=3),
        process_name=process,
        idle_seconds=0,
        keyboard_events=3,
        mouse_events=2,
        task_label="ML",
    )


def test_break_duration_policy() -> None:
    state = StateEstimate(
        focus_score=0.4,
        fatigue_score=0.7,
        fragmentation_score=0.5,
        break_need_score=0.9,
        continuous_work_minutes=95,
        time_since_last_break_minutes=100,
        switches_15m=20,
    )
    assert recommended_break_duration(state) == 15
    assert recommend_break(state, threshold=0.7, minimum_work_minutes=45).should_break


def test_recommendation_persists_notification_and_respects_cooldown(tmp_path) -> None:
    reset_engine()
    config = AppConfig(
        data_dir=tmp_path,
        collector=CollectorConfig(polling_interval_sec=1.0),
        intervention=InterventionConfig(risk_threshold=0.5, cooldown_minutes=30),
    )
    init_db(config.db_path)
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    for index in range(100):
        insert_event(_event(now - timedelta(minutes=90) + timedelta(minutes=index)), config.db_path)

    service = RecommendationService(config, RuntimeSettings())
    first = service.evaluate_now(now)
    assert first is not None
    assert first.intervention is not None
    assert first.notification is not None
    assert count_unread_notifications(config.db_path) == 1

    second = service.evaluate_now(now + timedelta(minutes=1))
    assert second is not None
    assert second.notification is None
    assert len(get_recent_interventions(db_path=config.db_path)) == 1


def test_notification_feedback_persistence(tmp_path) -> None:
    reset_engine()
    config = AppConfig(data_dir=tmp_path, intervention=InterventionConfig(risk_threshold=0.5))
    init_db(config.db_path)
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    for index in range(100):
        insert_event(_event(now - timedelta(minutes=90) + timedelta(minutes=index)), config.db_path)
    result = RecommendationService(config, RuntimeSettings()).evaluate_now(now)
    assert result is not None
    assert result.intervention is not None
    assert result.notification is not None

    notifications = get_notifications(db_path=config.db_path)
    assert notifications[0].state == NotificationState.UNREAD
    service = NotificationService(config.db_path)
    service.start_break(result.intervention.id or 0)
    service.mark_read(result.notification.id or 0)
    service.complete_break(result.intervention.id or 0, actual_minutes=12, feedback="yes")

    intervention = get_recent_interventions(db_path=config.db_path)[0]
    notification = get_notifications(db_path=config.db_path)[0]
    assert intervention.response == InterventionResponse.STARTED
    assert intervention.completed is True
    assert intervention.actual_break_duration_minutes == 12
    assert notification.state == NotificationState.READ


def test_model_unavailable_uses_baseline_fallback(tmp_path) -> None:
    reset_engine()
    config = AppConfig(data_dir=tmp_path, intervention=InterventionConfig(risk_threshold=0.5))
    init_db(config.db_path)
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    for index in range(80):
        insert_event(_event(now - timedelta(minutes=80) + timedelta(minutes=index)), config.db_path)
    result = RecommendationService(config, RuntimeSettings(), model=None).evaluate_now(now)
    assert result is not None
    assert result.recommendation.state.source == "baseline"
