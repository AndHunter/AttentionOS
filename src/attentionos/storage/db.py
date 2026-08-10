"""Database engine, session management, and CRUD helpers."""

from __future__ import annotations

import logging
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session as DBSession
from sqlmodel import SQLModel, create_engine, select

from attentionos.storage.schema import ActivityEvent, Intervention, SelfReport, Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine singleton
# ---------------------------------------------------------------------------

_engine = None


def get_engine(db_path: Path | str | None = None):
    """Create or return a cached SQLAlchemy engine.

    Uses WAL journal mode for better concurrent read/write performance.
    """
    global _engine
    if _engine is None:
        if db_path is None:
            from attentionos.config import get_config

            db_path = get_config().db_path

        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        url = f"sqlite:///{db_path}"
        _engine = create_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        # Enable WAL mode for better concurrency
        with _engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
            conn.exec_driver_sql("PRAGMA cache_size=-64000")  # 64 MB
            conn.commit()

        logger.info("Database engine created: %s", url)
    return _engine


def init_db(db_path: Path | str | None = None) -> None:
    """Create all tables if they don't exist yet."""
    engine = get_engine(db_path)
    SQLModel.metadata.create_all(engine)
    logger.info("Database tables initialized.")


def reset_engine() -> None:
    """Reset the cached engine (useful for testing)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


@contextmanager
def get_session(db_path: Path | str | None = None) -> Generator[DBSession, None, None]:
    """Provide a transactional database session scope."""
    engine = get_engine(db_path)
    with DBSession(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# ---------------------------------------------------------------------------
# CRUD — Activity Events
# ---------------------------------------------------------------------------


def insert_event(event: ActivityEvent, db_path: Path | str | None = None) -> ActivityEvent:
    """Insert a single activity event."""
    with get_session(db_path) as session:
        session.add(event)
        session.flush()
        session.refresh(event)
        session.expunge(event)
    return event


def insert_events_batch(
    events: list[ActivityEvent], db_path: Path | str | None = None
) -> int:
    """Insert a batch of activity events. Returns the number inserted."""
    if not events:
        return 0
    with get_session(db_path) as session:
        session.add_all(events)
    return len(events)


def get_events_range(
    start: datetime,
    end: datetime,
    db_path: Path | str | None = None,
) -> Sequence[ActivityEvent]:
    """Retrieve activity events within a time range (inclusive)."""
    with get_session(db_path) as session:
        stmt = (
            select(ActivityEvent)
            .where(ActivityEvent.ts_start >= start)
            .where(ActivityEvent.ts_end <= end)
            .order_by(ActivityEvent.ts_start)
        )
        results = session.exec(stmt).all()
        for r in results:
            session.expunge(r)
        return results


def get_daily_events(
    day: date | None = None,
    db_path: Path | str | None = None,
) -> Sequence[ActivityEvent]:
    """Retrieve all activity events for a given day (defaults to today)."""
    if day is None:
        day = date.today()
    start = datetime.combine(day, datetime.min.time())
    end = datetime.combine(day, datetime.max.time())
    return get_events_range(start, end, db_path)


# ---------------------------------------------------------------------------
# CRUD — Self Reports
# ---------------------------------------------------------------------------


def insert_self_report(
    report: SelfReport, db_path: Path | str | None = None
) -> SelfReport:
    """Insert a self-report entry."""
    with get_session(db_path) as session:
        session.add(report)
        session.flush()
        session.refresh(report)
        session.expunge(report)
    return report


def get_self_reports_range(
    start: datetime,
    end: datetime,
    db_path: Path | str | None = None,
) -> Sequence[SelfReport]:
    """Retrieve self-reports within a time range."""
    with get_session(db_path) as session:
        stmt = (
            select(SelfReport)
            .where(SelfReport.timestamp >= start)
            .where(SelfReport.timestamp <= end)
            .order_by(SelfReport.timestamp)
        )
        results = session.exec(stmt).all()
        for r in results:
            session.expunge(r)
        return results


# ---------------------------------------------------------------------------
# CRUD — Interventions
# ---------------------------------------------------------------------------


def insert_intervention(
    intervention: Intervention, db_path: Path | str | None = None
) -> Intervention:
    """Insert an intervention record."""
    with get_session(db_path) as session:
        session.add(intervention)
        session.flush()
        session.refresh(intervention)
        session.expunge(intervention)
    return intervention


# ---------------------------------------------------------------------------
# CRUD — Sessions
# ---------------------------------------------------------------------------


def insert_sessions_batch(
    sessions: list[Session], db_path: Path | str | None = None
) -> int:
    """Insert a batch of derived sessions. Returns the count inserted."""
    if not sessions:
        return 0
    with get_session(db_path) as session:
        session.add_all(sessions)
    return len(sessions)


def get_sessions_range(
    start: datetime,
    end: datetime,
    db_path: Path | str | None = None,
) -> Sequence[Session]:
    """Retrieve sessions within a time range."""
    with get_session(db_path) as session:
        stmt = (
            select(Session)
            .where(Session.ts_start >= start)
            .where(Session.ts_end <= end)
            .order_by(Session.ts_start)
        )
        results = session.exec(stmt).all()
        for r in results:
            session.expunge(r)
        return results
