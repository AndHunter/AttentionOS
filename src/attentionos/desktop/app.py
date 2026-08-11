"""Native Tkinter desktop app for AttentionOS."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from datetime import UTC, date, datetime
from tkinter import messagebox, ttk

from attentionos.collector.engine import CollectorEngine
from attentionos.config import AppConfig, get_config
from attentionos.desktop.components.diagnostics import DiagnosticsDrawer
from attentionos.desktop.components.self_report import SelfReportDialog
from attentionos.desktop.theme import COLORS, TYPOGRAPHY
from attentionos.desktop.view_model import build_dashboard_snapshot
from attentionos.desktop.views.dashboard import DashboardView
from attentionos.storage.db import get_daily_events, init_db, insert_self_report
from attentionos.storage.schema import SelfReport

logger = logging.getLogger(__name__)


class AttentionOSDesktopApp(tk.Tk):
    """Native desktop shell around the local-first telemetry engine."""

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config = config or get_config()
        self.config.ensure_dirs()
        init_db(self.config.db_path)

        self.title("AttentionOS")
        self.geometry("1180x760")
        self.minsize(1000, 700)
        self.configure(bg=COLORS.background)

        self.selected_date = date.today()
        self.collector: CollectorEngine | None = None
        self.collector_thread: threading.Thread | None = None
        self.collector_error: str | None = None
        self.diagnostics: DiagnosticsDrawer | None = None
        self.task_var = tk.StringVar(value="None")

        self._configure_styles()
        self.dashboard = DashboardView(
            self,
            task_var=self.task_var,
            task_labels=["None", *self.config.self_report.default_task_labels],
            callbacks={
                "task_change": self._sync_task_label,
                "start": self._start_collector,
                "stop": self._stop_collector,
                "check_in": self._open_self_report,
                "previous_day": self._previous_day,
                "next_day": self._next_day,
                "diagnostics": self._open_diagnostics,
            },
        )
        self.dashboard.pack(fill="both", expand=True)
        self._refresh_dashboard()
        self.after(1000, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=TYPOGRAPHY.body)
        style.configure("TFrame", background=COLORS.background)

    def _start_collector(self) -> None:
        if self.collector_thread and self.collector_thread.is_alive():
            return

        self.collector_error = None
        self.collector = CollectorEngine(self.config)
        self._sync_task_label()

        def _run() -> None:
            try:
                if self.collector is not None:
                    self.collector.run(register_signals=False)
            except Exception as exc:
                logger.exception("Collector crashed.")
                self.collector_error = str(exc)
                self.after(0, self._collector_failed)

        self.collector_thread = threading.Thread(
            target=_run,
            name="attentionos-desktop-collector",
            daemon=True,
        )
        self.collector_thread.start()
        self._update_tracking_status()

    def _stop_collector(self) -> None:
        if self.collector is not None:
            self.collector.stop()
        if self.collector_thread is not None:
            self.collector_thread.join(timeout=2.5)
        self._update_tracking_status()

    def _collector_failed(self) -> None:
        self._update_tracking_status()
        if self.collector_error:
            messagebox.showerror("AttentionOS", self.collector_error)

    def _sync_task_label(self) -> None:
        label = self.task_var.get()
        normalized = None if label == "None" else label
        if self.collector is not None:
            self.collector.set_task_label(normalized)

    def _previous_day(self) -> None:
        from datetime import timedelta

        self.selected_date -= timedelta(days=1)
        self._refresh_dashboard()

    def _next_day(self) -> None:
        from datetime import timedelta

        if self.selected_date < date.today():
            self.selected_date += timedelta(days=1)
            self._refresh_dashboard()

    def _open_self_report(self) -> None:
        SelfReportDialog(self, self._save_self_report)

    def _save_self_report(
        self,
        effectiveness: int,
        fatigue: int,
        difficulty: int | None,
        note: str | None,
    ) -> None:
        report = SelfReport(
            timestamp=datetime.now(tz=UTC),
            perceived_effectiveness=effectiveness,
            perceived_fatigue=fatigue,
            task_difficulty=difficulty,
            note=note,
        )
        try:
            insert_self_report(report, self.config.db_path)
        except Exception as exc:
            messagebox.showerror("AttentionOS", f"Could not save report: {exc}")
            return
        self._refresh_dashboard()

    def _open_diagnostics(self) -> None:
        if self.diagnostics is not None and self.diagnostics.winfo_exists():
            self.diagnostics.lift()
            return
        self.diagnostics = DiagnosticsDrawer(self, str(self.config.db_path))
        self._update_diagnostics()

    def _tick(self) -> None:
        self._update_tracking_status()
        self._update_diagnostics()
        self._refresh_dashboard()
        self.after(3000, self._tick)

    def _update_tracking_status(self) -> None:
        active = self.collector_thread is not None and self.collector_thread.is_alive()
        elapsed = "00:00:00"
        if active and self.collector is not None:
            uptime = int(self.collector.stats.get("uptime_seconds", 0))
            hours, remainder = divmod(uptime, 3600)
            minutes, seconds = divmod(remainder, 60)
            elapsed = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self.dashboard.set_tracking(active, elapsed)

    def _update_diagnostics(self) -> None:
        if self.diagnostics is None or not self.diagnostics.winfo_exists():
            return
        stats: dict[str, float | int]
        if self.collector is None:
            stats = {
                "total_events": 0,
                "input_hooks_running": 0,
                "last_keyboard_events": 0,
                "last_mouse_events": 0,
                "last_idle_seconds": 0.0,
            }
        else:
            stats = self.collector.stats
        self.diagnostics.set_stats(stats)

    def _refresh_dashboard(self) -> None:
        events = list(get_daily_events(self.selected_date, self.config.db_path))
        snapshot = build_dashboard_snapshot(events, self.selected_date)
        self.dashboard.apply_snapshot(snapshot)

    def _on_close(self) -> None:
        self._stop_collector()
        self.destroy()


def _setup_desktop_logging(config: AppConfig) -> None:
    config.ensure_dirs()
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.log_path, encoding="utf-8"),
        ],
    )


def main() -> None:
    """Launch the native desktop app."""
    config = get_config()
    _setup_desktop_logging(config)
    app = AttentionOSDesktopApp(config)
    app.mainloop()


if __name__ == "__main__":
    main()
