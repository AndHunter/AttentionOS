"""Notification center and intervention feedback service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from attentionos.storage.db import get_session
from attentionos.storage.schema import (
    Intervention,
    InterventionResponse,
    Notification,
    NotificationState,
)


class NotificationService:
    """Persist notification state and user responses."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path

    def mark_read(self, notification_id: int) -> None:
        with get_session(self.db_path) as session:
            notification = session.get(Notification, notification_id)
            if notification is not None:
                notification.state = NotificationState.READ
                session.add(notification)

    def dismiss(self, intervention_id: int | None, notification_id: int | None = None) -> None:
        with get_session(self.db_path) as session:
            if notification_id is not None:
                notification = session.get(Notification, notification_id)
                if notification is not None:
                    notification.state = NotificationState.DISMISSED
                    session.add(notification)
            if intervention_id is not None:
                intervention = session.get(Intervention, intervention_id)
                if intervention is not None:
                    intervention.dismissed = True
                    intervention.response = InterventionResponse.DISMISSED
                    session.add(intervention)

    def snooze(self, intervention_id: int, minutes: int = 10) -> None:
        with get_session(self.db_path) as session:
            intervention = session.get(Intervention, intervention_id)
            if intervention is not None:
                intervention.response = InterventionResponse.SNOOZED
                intervention.snoozed_until = datetime.now(tz=UTC) + timedelta(minutes=minutes)
                session.add(intervention)

    def start_break(self, intervention_id: int) -> None:
        with get_session(self.db_path) as session:
            intervention = session.get(Intervention, intervention_id)
            if intervention is not None:
                intervention.accepted = True
                intervention.response = InterventionResponse.STARTED
                intervention.break_started_at = datetime.now(tz=UTC)
                session.add(intervention)

    def complete_break(
        self,
        intervention_id: int,
        actual_minutes: int,
        feedback: str | None = None,
    ) -> None:
        with get_session(self.db_path) as session:
            intervention = session.get(Intervention, intervention_id)
            if intervention is not None:
                intervention.completed = True
                intervention.actual_break_duration_minutes = actual_minutes
                intervention.feedback_after_break = feedback
                session.add(intervention)
