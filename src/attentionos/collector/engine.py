"""Collector engine — main collection loop orchestrating all trackers."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import UTC, datetime

from attentionos.collector.foreground import ForegroundTracker
from attentionos.collector.idle import IdleTracker
from attentionos.collector.input_activity import InputCounter
from attentionos.config import AppConfig, get_config
from attentionos.storage.db import init_db, insert_events_batch
from attentionos.storage.schema import ActivityEvent

logger = logging.getLogger(__name__)


class CollectorEngine:
    """Main telemetry collection loop.

    Orchestrates foreground tracking, idle detection, and input counting.
    Batches events and flushes them to SQLite periodically.
    Handles graceful shutdown via signals and sleep/wake detection.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or get_config()
        self._foreground = ForegroundTracker(
            hash_titles=not self._config.collector.store_window_titles
        )
        self._idle = IdleTracker(
            idle_threshold_sec=self._config.collector.idle_threshold_sec
        )
        self._input = InputCounter()

        self._batch: list[ActivityEvent] = []
        self._last_flush_time: float = time.monotonic()
        self._running = False
        self._current_task_label: str | None = None
        self._last_event: ActivityEvent | None = None

        # Statistics
        self._total_events: int = 0
        self._total_flushes: int = 0
        self._start_time: float = 0.0

    # -----------------------------------------------------------------------
    # Task label (set externally by UI or CLI)
    # -----------------------------------------------------------------------

    def set_task_label(self, label: str | None) -> None:
        """Set the current task label for incoming events."""
        self._current_task_label = label
        logger.info("Task label set to: %s", label)

    # -----------------------------------------------------------------------
    # Core loop
    # -----------------------------------------------------------------------

    def _collect_one(self) -> ActivityEvent:
        """Perform a single collection cycle and return an ActivityEvent."""
        now = datetime.now(tz=UTC)

        # 1. Foreground window
        fg_info, _is_switch = self._foreground.poll()

        # 2. Idle state
        idle_sec, _is_idle, _became_idle = self._idle.poll()

        # 3. Input counts (since last poll)
        kb_count, mouse_count = self._input.get_and_reset()

        # 4. Build event
        event = ActivityEvent(
            ts_start=now,
            ts_end=now,  # Single-point observation
            process_name=fg_info.process_name,
            window_title_hash=fg_info.window_title_hash or None,
            idle_seconds=idle_sec,
            keyboard_events=kb_count,
            mouse_events=mouse_count,
            task_label=self._current_task_label,
            collector_version=self._config.collector_version,
        )

        self._last_event = event
        return event

    def _should_flush(self) -> bool:
        """Determine if the event batch should be flushed to the database."""
        batch_full = len(self._batch) >= self._config.collector.batch_size
        time_elapsed = (
            time.monotonic() - self._last_flush_time
            >= self._config.collector.batch_flush_interval_sec
        )
        return batch_full or (time_elapsed and len(self._batch) > 0)

    def _flush_batch(self) -> None:
        """Write accumulated events to the database."""
        if not self._batch:
            return
        try:
            count = insert_events_batch(self._batch)
            self._total_flushes += 1
            logger.debug("Flushed %d events to DB (total flushes: %d)", count, self._total_flushes)
        except Exception:
            logger.exception("Failed to flush events to database.")
        finally:
            self._batch.clear()
            self._last_flush_time = time.monotonic()

    def _detect_sleep_wake(self, last_tick: float) -> bool:
        """Detect if the system has resumed from sleep.

        If the time gap between ticks is much larger than expected,
        the system was likely sleeping.
        """
        now = time.monotonic()
        expected_gap = self._config.collector.polling_interval_sec
        actual_gap = now - last_tick

        # If actual gap is more than 3x expected, likely a sleep event
        if actual_gap > expected_gap * 3 and actual_gap > 10.0:
            logger.warning(
                "Possible sleep/wake detected: expected gap %.1fs, actual %.1fs",
                expected_gap,
                actual_gap,
            )
            return True
        return False

    def run(self, register_signals: bool = True) -> None:
        """Start the main collection loop.

        Runs until interrupted by SIGINT/SIGTERM or self.stop() is called.
        """
        self._running = True
        self._start_time = time.monotonic()

        # Initialize database
        init_db(self._config.db_path)

        # Start input hooks
        self._input.start()

        if register_signals:
            # Signal handlers can only be installed from the main thread.
            def _shutdown_handler(signum: int, frame: object) -> None:
                logger.info("Received signal %d, shutting down...", signum)
                self._running = False

            signal.signal(signal.SIGINT, _shutdown_handler)
            signal.signal(signal.SIGTERM, _shutdown_handler)

        logger.info(
            "Collector started (interval=%.1fs, idle_threshold=%.0fs, batch_size=%d)",
            self._config.collector.polling_interval_sec,
            self._config.collector.idle_threshold_sec,
            self._config.collector.batch_size,
        )

        last_tick = time.monotonic()

        try:
            while self._running:
                loop_start = time.monotonic()

                # Detect sleep/wake
                if self._detect_sleep_wake(last_tick):
                    # Flush anything pending before the gap
                    self._flush_batch()

                # Collect one event
                try:
                    event = self._collect_one()
                    self._batch.append(event)
                    self._total_events += 1
                except Exception:
                    logger.exception("Error during collection.")

                # Flush if needed
                if self._should_flush():
                    self._flush_batch()

                last_tick = time.monotonic()

                # Sleep until next polling interval
                elapsed = time.monotonic() - loop_start
                sleep_time = max(0.0, self._config.collector.polling_interval_sec - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            # Final flush on shutdown
            self._flush_batch()
            self._input.stop()

            uptime = time.monotonic() - self._start_time
            logger.info(
                "Collector stopped. Uptime: %.0fs, Events: %d, Flushes: %d",
                uptime,
                self._total_events,
                self._total_flushes,
            )

    def stop(self) -> None:
        """Signal the collector loop to stop."""
        self._running = False

    @property
    def stats(self) -> dict[str, float | int]:
        """Return current collector statistics."""
        uptime = time.monotonic() - self._start_time if self._start_time else 0.0
        last_event = self._last_event
        return {
            "uptime_seconds": uptime,
            "total_events": self._total_events,
            "total_flushes": self._total_flushes,
            "pending_batch_size": len(self._batch),
            "context_switches": self._foreground.context_switch_count,
            "idle_bursts": self._idle.idle_burst_count,
            "is_idle": self._idle.is_idle,
            "input_hooks_running": int(self._input.is_running),
            "last_keyboard_events": last_event.keyboard_events if last_event else 0,
            "last_mouse_events": last_event.mouse_events if last_event else 0,
            "last_idle_seconds": last_event.idle_seconds if last_event else 0.0,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _setup_logging(config: AppConfig) -> None:
    """Configure logging for the collector process."""
    config.ensure_dirs()
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.log_path, encoding="utf-8"),
        ],
    )


def main() -> None:
    """CLI entry point: `attentionos-collect`."""
    config = get_config()
    _setup_logging(config)

    logger.info("=" * 60)
    logger.info("AttentionOS Collector v%s starting...", config.collector_version)
    logger.info("Data directory: %s", config.data_dir)
    logger.info("Database: %s", config.db_path)
    logger.info("=" * 60)

    engine = CollectorEngine(config)
    engine.run()


if __name__ == "__main__":
    main()
