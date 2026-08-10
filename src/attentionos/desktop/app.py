"""Native Tkinter desktop app for AttentionOS."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from datetime import UTC, date, datetime, timedelta
from tkinter import messagebox, ttk

from attentionos.collector.engine import CollectorEngine
from attentionos.config import AppConfig, get_config
from attentionos.desktop.view_model import (
    DashboardSnapshot,
    build_dashboard_snapshot,
    clean_app_name,
    format_duration,
)
from attentionos.storage.db import (
    get_daily_events,
    get_self_reports_range,
    init_db,
    insert_self_report,
)
from attentionos.storage.schema import SelfReport, Session

logger = logging.getLogger(__name__)


class Palette:
    """Calm, high-contrast palette tuned for long desktop sessions."""

    APP_BG = "#f5f1ea"
    SURFACE = "#fffdf8"
    SURFACE_ALT = "#ebe4d9"
    SIDEBAR = "#1f2925"
    SIDEBAR_ALT = "#2c3a34"
    TEXT = "#202621"
    MUTED = "#68716a"
    INVERTED = "#f7f2e9"
    BORDER = "#d9d0c3"
    ACCENT = "#2f7d72"
    ACCENT_DARK = "#235f57"
    FOCUS = "#c86d45"
    WARNING = "#b3862f"
    DANGER = "#a94f4a"
    IDLE = "#aaa59c"


APP_COLORS = [
    "#2f7d72",
    "#c86d45",
    "#5f6f52",
    "#b3862f",
    "#6d5f8f",
    "#7f5a4b",
    "#4e777d",
    "#8a6240",
]


class AttentionOSDesktopApp(tk.Tk):
    """Native desktop shell around the local-first telemetry engine."""

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config = config or get_config()
        self.config.ensure_dirs()
        init_db(self.config.db_path)

        self.title("AttentionOS")
        self.geometry("1180x760")
        self.minsize(980, 660)
        self.configure(bg=Palette.APP_BG)

        self.selected_date = date.today()
        self.collector: CollectorEngine | None = None
        self.collector_thread: threading.Thread | None = None
        self.collector_error: str | None = None

        self.status_var = tk.StringVar(value="Stopped")
        self.task_var = tk.StringVar(value="None")
        self.date_var = tk.StringVar()
        self.live_var = tk.StringVar(value="Events 0 | Hooks off | Keys 0 | Mouse 0")
        self.effectiveness_var = tk.IntVar(value=3)
        self.fatigue_var = tk.IntVar(value=2)
        self.difficulty_var = tk.IntVar(value=0)
        self.report_status_var = tk.StringVar(value="")

        self.metric_value_vars: dict[str, tk.StringVar] = {}
        self.metric_label_vars: dict[str, tk.StringVar] = {}

        self._configure_styles()
        self._build_layout()
        self._set_date_label()
        self._refresh_dashboard()
        self.after(1000, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=Palette.APP_BG)
        style.configure("Surface.TFrame", background=Palette.SURFACE, relief="flat")
        style.configure("Sidebar.TFrame", background=Palette.SIDEBAR)
        style.configure("Title.TLabel", background=Palette.SURFACE, foreground=Palette.TEXT)
        style.configure(
            "SidebarTitle.TLabel",
            background=Palette.SIDEBAR,
            foreground=Palette.INVERTED,
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "SidebarText.TLabel",
            background=Palette.SIDEBAR,
            foreground="#cbd5cb",
            font=("Segoe UI", 9),
        )
        style.configure(
            "H1.TLabel",
            background=Palette.APP_BG,
            foreground=Palette.TEXT,
            font=("Segoe UI", 22, "bold"),
        )
        style.configure(
            "H2.TLabel",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background=Palette.SURFACE,
            foreground=Palette.MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "MetricValue.TLabel",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
            font=("Segoe UI", 22, "bold"),
        )
        style.configure(
            "MetricLabel.TLabel",
            background=Palette.SURFACE,
            foreground=Palette.MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Accent.TButton",
            background=Palette.ACCENT,
            foreground="white",
            bordercolor=Palette.ACCENT_DARK,
            focusthickness=0,
            padding=(12, 9),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", Palette.ACCENT_DARK), ("disabled", Palette.SURFACE_ALT)],
        )
        style.configure(
            "Ghost.TButton",
            background=Palette.SIDEBAR_ALT,
            foreground=Palette.INVERTED,
            bordercolor=Palette.SIDEBAR_ALT,
            focusthickness=0,
            padding=(10, 8),
            font=("Segoe UI", 10),
        )
        style.map("Ghost.TButton", background=[("active", "#394a43")])
        style.configure(
            "Treeview",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
            fieldbackground=Palette.SURFACE,
            bordercolor=Palette.BORDER,
            rowheight=28,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background=Palette.SURFACE_ALT,
            foreground=Palette.TEXT,
            font=("Segoe UI", 9, "bold"),
        )

    def _build_layout(self) -> None:
        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(root, width=270, style="Sidebar.TFrame")
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)

        self.content = ttk.Frame(root, style="App.TFrame", padding=(24, 22, 24, 18))
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(3, weight=1)

        self._build_sidebar()
        self._build_header()
        self._build_metrics()
        self._build_charts()
        self._build_tables()

    def _build_sidebar(self) -> None:
        pad = {"padx": 22, "pady": 8}

        ttk.Label(self.sidebar, text="AttentionOS", style="SidebarTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=22, pady=(28, 2)
        )
        ttk.Label(
            self.sidebar,
            text="Native Windows focus tracker",
            style="SidebarText.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 24))

        status_box = tk.Frame(self.sidebar, bg=Palette.SIDEBAR_ALT, highlightthickness=0)
        status_box.grid(row=2, column=0, sticky="ew", **pad)
        status_box.columnconfigure(1, weight=1)
        self.status_dot = tk.Canvas(
            status_box,
            width=16,
            height=16,
            bg=Palette.SIDEBAR_ALT,
            bd=0,
            highlightthickness=0,
        )
        self.status_dot.grid(row=0, column=0, padx=(14, 8), pady=14)
        self.status_dot_id = self.status_dot.create_oval(
            3,
            3,
            13,
            13,
            fill=Palette.IDLE,
            outline="",
        )
        tk.Label(
            status_box,
            textvariable=self.status_var,
            bg=Palette.SIDEBAR_ALT,
            fg=Palette.INVERTED,
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=1, sticky="w", pady=14)

        ttk.Label(self.sidebar, text="Current task", style="SidebarText.TLabel").grid(
            row=3, column=0, sticky="w", **pad
        )
        labels = ["None", *self.config.self_report.default_task_labels]
        task_combo = ttk.Combobox(
            self.sidebar,
            textvariable=self.task_var,
            values=labels,
            state="readonly",
            font=("Segoe UI", 10),
        )
        task_combo.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 14))
        task_combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_task_label())

        self.start_button = ttk.Button(
            self.sidebar,
            text="Start tracking",
            style="Accent.TButton",
            command=self._start_collector,
        )
        self.start_button.grid(row=5, column=0, sticky="ew", padx=22, pady=(6, 8))
        self.stop_button = ttk.Button(
            self.sidebar,
            text="Stop",
            style="Ghost.TButton",
            command=self._stop_collector,
            state="disabled",
        )
        self.stop_button.grid(row=6, column=0, sticky="ew", padx=22, pady=(0, 24))

        ttk.Label(self.sidebar, text="Day", style="SidebarText.TLabel").grid(
            row=7, column=0, sticky="w", **pad
        )
        date_row = tk.Frame(self.sidebar, bg=Palette.SIDEBAR)
        date_row.grid(row=8, column=0, sticky="ew", padx=22, pady=(0, 8))
        date_row.columnconfigure(1, weight=1)
        ttk.Button(date_row, text="<", style="Ghost.TButton", command=self._previous_day).grid(
            row=0, column=0, sticky="ew"
        )
        tk.Label(
            date_row,
            textvariable=self.date_var,
            bg=Palette.SIDEBAR,
            fg=Palette.INVERTED,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(date_row, text=">", style="Ghost.TButton", command=self._next_day).grid(
            row=0, column=2, sticky="ew"
        )

        ttk.Button(
            self.sidebar,
            text="Refresh",
            style="Ghost.TButton",
            command=self._refresh_dashboard,
        ).grid(row=9, column=0, sticky="ew", padx=22, pady=(0, 22))

        tk.Label(
            self.sidebar,
            textvariable=self.live_var,
            bg=Palette.SIDEBAR,
            fg="#d6dfd5",
            wraplength=220,
            justify="left",
            font=("Segoe UI", 9),
        ).grid(row=10, column=0, sticky="ew", padx=22, pady=(2, 12))

        data_text = f"SQLite\n{self.config.db_path}"
        tk.Label(
            self.sidebar,
            text=data_text,
            bg=Palette.SIDEBAR,
            fg="#9daf9f",
            wraplength=220,
            justify="left",
            font=("Segoe UI", 8),
        ).grid(row=11, column=0, sticky="w", padx=22, pady=(18, 8))

    def _build_header(self) -> None:
        header = ttk.Frame(self.content, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Daily Focus Console", style="H1.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.subtitle_var = tk.StringVar(value="")
        ttk.Label(
            header,
            textvariable=self.subtitle_var,
            background=Palette.APP_BG,
            foreground=Palette.MUTED,
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_metrics(self) -> None:
        grid = ttk.Frame(self.content, style="App.TFrame")
        grid.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        for idx in range(5):
            grid.columnconfigure(idx, weight=1, uniform="metrics")

        metric_keys = [
            ("active", "Active time"),
            ("focus", "Focus blocks"),
            ("avg", "Avg focus"),
            ("switches", "Switches"),
            ("inputs", "Input events"),
        ]
        for idx, (key, label) in enumerate(metric_keys):
            frame = tk.Frame(
                grid,
                bg=Palette.SURFACE,
                highlightbackground=Palette.BORDER,
                highlightthickness=1,
            )
            frame.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0), ipady=10)
            frame.columnconfigure(0, weight=1)
            self.metric_value_vars[key] = tk.StringVar(value="0")
            self.metric_label_vars[key] = tk.StringVar(value=label)
            ttk.Label(
                frame,
                textvariable=self.metric_value_vars[key],
                style="MetricValue.TLabel",
            ).grid(
                row=0, column=0, sticky="w", padx=16, pady=(12, 2)
            )
            ttk.Label(
                frame,
                textvariable=self.metric_label_vars[key],
                style="MetricLabel.TLabel",
            ).grid(
                row=1, column=0, sticky="w", padx=16, pady=(0, 12)
            )

    def _build_charts(self) -> None:
        chart_grid = ttk.Frame(self.content, style="App.TFrame")
        chart_grid.grid(row=2, column=0, sticky="ew", pady=(0, 18))
        chart_grid.columnconfigure(0, weight=3)
        chart_grid.columnconfigure(1, weight=2)

        timeline_panel = tk.Frame(
            chart_grid,
            bg=Palette.SURFACE,
            highlightbackground=Palette.BORDER,
            highlightthickness=1,
        )
        timeline_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        timeline_panel.columnconfigure(0, weight=1)
        ttk.Label(timeline_panel, text="Timeline", style="H2.TLabel").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 0)
        )
        self.timeline_canvas = tk.Canvas(
            timeline_panel,
            height=160,
            bg=Palette.SURFACE,
            bd=0,
            highlightthickness=0,
        )
        self.timeline_canvas.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 16))
        self.timeline_canvas.bind("<Configure>", lambda _event: self._draw_current_snapshot())

        apps_panel = tk.Frame(
            chart_grid,
            bg=Palette.SURFACE,
            highlightbackground=Palette.BORDER,
            highlightthickness=1,
        )
        apps_panel.grid(row=0, column=1, sticky="nsew")
        apps_panel.columnconfigure(0, weight=1)
        ttk.Label(apps_panel, text="Top apps", style="H2.TLabel").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 0)
        )
        self.apps_canvas = tk.Canvas(
            apps_panel,
            height=160,
            bg=Palette.SURFACE,
            bd=0,
            highlightthickness=0,
        )
        self.apps_canvas.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 16))
        self.apps_canvas.bind("<Configure>", lambda _event: self._draw_current_snapshot())

    def _build_tables(self) -> None:
        lower = ttk.Frame(self.content, style="App.TFrame")
        lower.grid(row=3, column=0, sticky="nsew")
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(0, weight=1)

        sessions_panel = tk.Frame(
            lower,
            bg=Palette.SURFACE,
            highlightbackground=Palette.BORDER,
            highlightthickness=1,
        )
        sessions_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        sessions_panel.columnconfigure(0, weight=1)
        sessions_panel.rowconfigure(1, weight=1)
        ttk.Label(sessions_panel, text="Recent sessions", style="H2.TLabel").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 8)
        )
        self.sessions_tree = ttk.Treeview(
            sessions_panel,
            columns=("time", "app", "duration", "keys", "mouse"),
            show="headings",
            height=9,
        )
        headings = {
            "time": "Time",
            "app": "App",
            "duration": "Duration",
            "keys": "Keys",
            "mouse": "Mouse",
        }
        widths = {"time": 120, "app": 180, "duration": 90, "keys": 70, "mouse": 70}
        for column, text in headings.items():
            self.sessions_tree.heading(column, text=text)
            self.sessions_tree.column(column, width=widths[column], anchor="w")
        self.sessions_tree.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        report_panel = tk.Frame(
            lower,
            bg=Palette.SURFACE,
            highlightbackground=Palette.BORDER,
            highlightthickness=1,
        )
        report_panel.grid(row=0, column=1, sticky="nsew")
        report_panel.columnconfigure(0, weight=1)
        ttk.Label(report_panel, text="Self-report", style="H2.TLabel").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 8)
        )
        form = tk.Frame(report_panel, bg=Palette.SURFACE)
        form.grid(row=1, column=0, sticky="ew", padx=16)
        form.columnconfigure(1, weight=1)
        self._add_spin_row(form, 0, "Effectiveness", self.effectiveness_var, 1, 5)
        self._add_spin_row(form, 1, "Fatigue", self.fatigue_var, 1, 5)
        self._add_spin_row(form, 2, "Difficulty", self.difficulty_var, 0, 5)
        ttk.Label(form, text="Note", style="Body.TLabel").grid(row=3, column=0, sticky="w", pady=7)
        self.note_entry = ttk.Entry(form, font=("Segoe UI", 10))
        self.note_entry.grid(row=3, column=1, sticky="ew", pady=7)
        ttk.Button(
            report_panel,
            text="Save report",
            style="Accent.TButton",
            command=self._save_self_report,
        ).grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 8))
        tk.Label(
            report_panel,
            textvariable=self.report_status_var,
            bg=Palette.SURFACE,
            fg=Palette.MUTED,
            wraplength=320,
            justify="left",
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        self.report_history = tk.Text(
            report_panel,
            height=7,
            bg=Palette.SURFACE,
            fg=Palette.TEXT,
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 9),
            wrap="word",
        )
        self.report_history.grid(row=4, column=0, sticky="nsew", padx=16, pady=(0, 16))

    @staticmethod
    def _add_spin_row(
        parent: tk.Widget,
        row: int,
        label: str,
        variable: tk.IntVar,
        from_: int,
        to: int,
    ) -> None:
        ttk.Label(parent, text=label, style="Body.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
            pady=7,
        )
        spin = ttk.Spinbox(parent, from_=from_, to=to, textvariable=variable, width=6)
        spin.grid(row=row, column=1, sticky="w", pady=7)

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
        self.status_var.set("Tracking")
        self.status_dot.itemconfigure(self.status_dot_id, fill=Palette.ACCENT)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def _stop_collector(self) -> None:
        if self.collector is not None:
            self.collector.stop()
        if self.collector_thread is not None:
            self.collector_thread.join(timeout=2.5)
        self.status_var.set("Stopped")
        self.status_dot.itemconfigure(self.status_dot_id, fill=Palette.IDLE)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _collector_failed(self) -> None:
        self.status_var.set("Collector error")
        self.status_dot.itemconfigure(self.status_dot_id, fill=Palette.DANGER)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if self.collector_error:
            messagebox.showerror("AttentionOS", self.collector_error)

    def _sync_task_label(self) -> None:
        label = self.task_var.get()
        normalized = None if label == "None" else label
        if self.collector is not None:
            self.collector.set_task_label(normalized)

    def _previous_day(self) -> None:
        self.selected_date -= timedelta(days=1)
        self._set_date_label()
        self._refresh_dashboard()

    def _next_day(self) -> None:
        if self.selected_date < date.today():
            self.selected_date += timedelta(days=1)
            self._set_date_label()
            self._refresh_dashboard()

    def _set_date_label(self) -> None:
        self.date_var.set(self.selected_date.strftime("%b %d"))
        self.subtitle_var.set(
            f"{self.selected_date.strftime('%A, %B %d, %Y')} | local telemetry only"
        )

    def _tick(self) -> None:
        self._update_live_status()
        self._refresh_dashboard()
        self.after(3000, self._tick)

    def _update_live_status(self) -> None:
        if self.collector is None:
            self.live_var.set("Events 0 | Hooks off | Keys 0 | Mouse 0")
            return
        stats = self.collector.stats
        hooks = "on" if stats["input_hooks_running"] else "off"
        self.live_var.set(
            (
                "Events {total_events} | Hooks {hooks} | Keys {keys} | "
                "Mouse {mouse} | Idle {idle:.0f}s"
            ).format(
                total_events=stats["total_events"],
                hooks=hooks,
                keys=stats["last_keyboard_events"],
                mouse=stats["last_mouse_events"],
                idle=float(stats["last_idle_seconds"]),
            )
        )

    def _refresh_dashboard(self) -> None:
        events = list(get_daily_events(self.selected_date, self.config.db_path))
        self.current_snapshot = build_dashboard_snapshot(events, self.selected_date)
        self._apply_snapshot(self.current_snapshot)

    def _apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        summary = snapshot.summary
        self.metric_value_vars["active"].set(format_duration(summary.total_active_seconds))
        self.metric_value_vars["focus"].set(str(summary.focus_sessions))
        self.metric_value_vars["avg"].set(format_duration(summary.mean_focus_block_sec))
        self.metric_value_vars["switches"].set(str(summary.total_context_switches))
        self.metric_value_vars["inputs"].set(
            str(summary.total_keyboard_events + summary.total_mouse_events)
        )
        self._draw_current_snapshot()
        self._fill_sessions(snapshot.sessions)
        self._fill_report_history()

    def _draw_current_snapshot(self) -> None:
        snapshot = getattr(self, "current_snapshot", None)
        if snapshot is None:
            return
        self._draw_timeline(snapshot)
        self._draw_apps(snapshot)

    def _draw_timeline(self, snapshot: DashboardSnapshot) -> None:
        canvas = self.timeline_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 520)
        left = 44
        right = width - 16
        track_y = 72
        track_h = 34
        canvas.create_rectangle(
            left,
            track_y,
            right,
            track_y + track_h,
            fill=Palette.SURFACE_ALT,
            outline="",
        )

        for hour in range(0, 25, 3):
            x = left + (right - left) * (hour / 24)
            canvas.create_line(x, track_y - 10, x, track_y + track_h + 12, fill=Palette.BORDER)
            canvas.create_text(
                x,
                track_y + track_h + 24,
                text=f"{hour:02d}:00",
                fill=Palette.MUTED,
                font=("Segoe UI", 8),
            )

        if not snapshot.sessions:
            canvas.create_text(
                width / 2,
                track_y + 16,
                text="No telemetry yet for this day",
                fill=Palette.MUTED,
                font=("Segoe UI", 10),
            )
            return

        color_map: dict[str, str] = {}
        day_start = datetime.combine(snapshot.target_date, datetime.min.time())
        day_seconds = 24 * 60 * 60
        for session in snapshot.sessions:
            start = max((session.ts_start.replace(tzinfo=None) - day_start).total_seconds(), 0)
            end = max((session.ts_end.replace(tzinfo=None) - day_start).total_seconds(), start + 1)
            x1 = left + (right - left) * min(start / day_seconds, 1)
            x2 = left + (right - left) * min(end / day_seconds, 1)
            if x2 - x1 < 2:
                x2 = x1 + 2
            color = (
                Palette.IDLE
                if session.is_idle
                else self._app_color(session.process_name, color_map)
            )
            canvas.create_rectangle(x1, track_y, x2, track_y + track_h, fill=color, outline="")
            if session.is_focus:
                canvas.create_rectangle(
                    x1,
                    track_y - 5,
                    x2,
                    track_y - 1,
                    fill=Palette.FOCUS,
                    outline="",
                )

    def _draw_apps(self, snapshot: DashboardSnapshot) -> None:
        canvas = self.apps_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        top_apps = [(name, seconds) for name, seconds in snapshot.summary.top_apps[:5]]
        if not top_apps:
            canvas.create_text(
                width / 2,
                76,
                text="No active apps yet",
                fill=Palette.MUTED,
                font=("Segoe UI", 10),
            )
            return

        max_seconds = max(seconds for _name, seconds in top_apps) or 1
        bar_left = 92
        bar_right = width - 18
        color_map: dict[str, str] = {}
        for idx, (name, seconds) in enumerate(top_apps):
            y = 20 + idx * 26
            label = clean_app_name(name)[:14]
            canvas.create_text(
                8,
                y + 8,
                text=label,
                anchor="w",
                fill=Palette.TEXT,
                font=("Segoe UI", 8),
            )
            canvas.create_rectangle(
                bar_left,
                y,
                bar_right,
                y + 16,
                fill=Palette.SURFACE_ALT,
                outline="",
            )
            x2 = bar_left + (bar_right - bar_left) * (seconds / max_seconds)
            canvas.create_rectangle(
                bar_left,
                y,
                x2,
                y + 16,
                fill=self._app_color(name, color_map),
                outline="",
            )
            canvas.create_text(
                bar_right,
                y + 8,
                text=format_duration(seconds),
                anchor="e",
                fill=Palette.TEXT,
                font=("Segoe UI", 8, "bold"),
            )

    @staticmethod
    def _app_color(name: str, color_map: dict[str, str]) -> str:
        if name not in color_map:
            color_map[name] = APP_COLORS[len(color_map) % len(APP_COLORS)]
        return color_map[name]

    def _fill_sessions(self, sessions: list[Session]) -> None:
        self.sessions_tree.delete(*self.sessions_tree.get_children())
        for session in reversed(sessions[-12:]):
            self.sessions_tree.insert(
                "",
                "end",
                values=(
                    f"{session.ts_start.strftime('%H:%M')} - {session.ts_end.strftime('%H:%M')}",
                    clean_app_name(session.process_name),
                    format_duration(session.duration_seconds),
                    session.total_keyboard_events,
                    session.total_mouse_events,
                ),
            )

    def _save_self_report(self) -> None:
        note = self.note_entry.get().strip()
        report = SelfReport(
            timestamp=datetime.now(tz=UTC),
            perceived_effectiveness=self.effectiveness_var.get(),
            perceived_fatigue=self.fatigue_var.get(),
            task_difficulty=self.difficulty_var.get() or None,
            note=note or None,
        )
        try:
            insert_self_report(report, self.config.db_path)
        except Exception as exc:
            messagebox.showerror("AttentionOS", f"Could not save report: {exc}")
            return
        self.note_entry.delete(0, tk.END)
        self.report_status_var.set("Saved at " + datetime.now().strftime("%H:%M"))
        self._fill_report_history()

    def _fill_report_history(self) -> None:
        day_start = datetime.combine(self.selected_date, datetime.min.time())
        day_end = datetime.combine(self.selected_date, datetime.max.time())
        reports = get_self_reports_range(day_start, day_end, self.config.db_path)
        self.report_history.configure(state="normal")
        self.report_history.delete("1.0", tk.END)
        if not reports:
            self.report_history.insert(tk.END, "No reports for this day.")
        else:
            for report in reversed(reports[-6:]):
                note = f" | {report.note}" if report.note else ""
                self.report_history.insert(
                    tk.END,
                    (
                        f"{report.timestamp.strftime('%H:%M')}  "
                        f"Effect {report.perceived_effectiveness}/5  "
                        f"Fatigue {report.perceived_fatigue}/5{note}\n"
                    ),
                )
        self.report_history.configure(state="disabled")

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
