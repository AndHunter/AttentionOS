"""Main dashboard view."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from attentionos.desktop.components.app_list import TopAppsList
from attentionos.desktop.components.base import Card, Pill, TextButton, draw_rounded_rect
from attentionos.desktop.components.metric_card import MetricCard
from attentionos.desktop.components.sessions_list import RecentSessionsList
from attentionos.desktop.components.timeline import Timeline
from attentionos.desktop.components.tracking_control import TrackingControl
from attentionos.desktop.formatting import format_duration, format_long_date
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.desktop.view_model import (
    DashboardSnapshot,
    build_top_apps,
)
from attentionos.localization import Translator
from attentionos.sessions.metrics import DailySummary


class ActivityPattern(Card):
    """Simple focus/activity pattern chart from existing switch windows."""

    def __init__(self, master: tk.Misc, translator: Translator) -> None:
        super().__init__(master, padding=SPACING.lg)
        self.translator = translator
        tk.Label(
            self.inner,
            text=translator.t("dashboard.activity_pattern"),
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.section,
        ).pack(anchor="w")
        self.canvas = tk.Canvas(
            self.inner,
            height=150,
            bg=COLORS.surface,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True, pady=(SPACING.md, 0))
        self.switch_windows: list[tuple[int, int]] = []
        self.canvas.bind("<Configure>", lambda _event: self.draw())

    def set_data(self, switch_windows: list[tuple[int, int]]) -> None:
        self.switch_windows = switch_windows
        self.draw()

    def draw(self) -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 300)
        height = max(self.canvas.winfo_height(), 130)
        left = 22
        right = width - 18
        bottom = height - 26
        top = 18
        self.canvas.create_line(left, bottom, right, bottom, fill=COLORS.border)
        if not self.switch_windows:
            self.canvas.create_text(
                width / 2,
                height / 2,
                text=self.translator.t("dashboard.activity_empty"),
                fill=COLORS.text_secondary,
                font=TYPOGRAPHY.caption,
            )
            return
        max_count = max(count for _minute, count in self.switch_windows) or 1
        step = (right - left) / max(len(self.switch_windows), 1)
        for idx, (_minute, count) in enumerate(self.switch_windows):
            x1 = left + idx * step + 4
            x2 = left + (idx + 1) * step - 4
            bar_h = (bottom - top) * (count / max_count)
            draw_rounded_rect(
                self.canvas,
                x1,
                bottom - bar_h,
                x2,
                bottom,
                radius=6,
                fill=COLORS.accent,
                outline="",
            )


class DashboardView(tk.Frame):
    """Composable dashboard presentation layer."""

    def __init__(
        self,
        master: tk.Misc,
        task_var: tk.StringVar,
        task_labels: list[str],
        callbacks: dict[str, Callable[[], None]],
        translator: Translator,
    ) -> None:
        super().__init__(master, bg=COLORS.background)
        self.callbacks = callbacks
        self.translator = translator
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)
        self.rowconfigure(3, weight=2)

        self._build_top_bar()
        self._build_hero(task_var, task_labels)
        self.timeline = Timeline(self, callbacks["previous_day"], callbacks["next_day"], translator)
        self.timeline.grid(row=2, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.md))
        self._build_secondary()

    def _build_top_bar(self) -> None:
        bar = tk.Frame(self, bg=COLORS.background)
        bar.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.lg, SPACING.md))
        bar.columnconfigure(0, weight=1)
        tk.Label(
            bar,
            text=self.translator.t("dashboard.title"),
            bg=COLORS.background,
            fg=COLORS.text,
            font=TYPOGRAPHY.page_title,
        ).grid(row=0, column=0, sticky="w")
        self.date_label = tk.StringVar(value="")
        tk.Label(
            bar,
            textvariable=self.date_label,
            bg=COLORS.background,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.body,
        ).grid(row=1, column=0, sticky="w", pady=(SPACING.xxs, 0))
        right = tk.Frame(bar, bg=COLORS.background)
        right.grid(row=0, column=1, rowspan=2, sticky="e")
        self.top_status_var = tk.StringVar(value=self.translator.t("tracking.status.stopped"))
        self.top_status = Pill(right, self.top_status_var)
        self.top_status.pack(side="left", padx=(0, SPACING.xs))
        self.privacy_var = tk.StringVar(value=self.translator.t("app.local_only"))
        tk.Label(
            right,
            textvariable=self.privacy_var,
            bg=COLORS.accent_soft,
            fg=COLORS.accent,
            font=TYPOGRAPHY.caption_semibold,
            padx=SPACING.sm,
            pady=SPACING.xs,
        ).pack(side="left", padx=(0, SPACING.xs))
        TextButton(
            right,
            self.translator.t("app.settings"),
            self.callbacks["settings"],
        ).pack(side="left")

    def _build_hero(self, task_var: tk.StringVar, task_labels: list[str]) -> None:
        hero = tk.Frame(self, bg=COLORS.background)
        hero.grid(row=1, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.md))
        hero.columnconfigure(0, weight=2)
        hero.columnconfigure(1, weight=1)

        self.tracking = TrackingControl(
            hero,
            task_var=task_var,
            labels=task_labels,
            on_task_change=self.callbacks["task_change"],
            on_start=self.callbacks["start"],
            on_stop=self.callbacks["stop"],
            on_check_in=self.callbacks["check_in"],
            translator=self.translator,
        )
        self.tracking.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.md))

        grid = tk.Frame(hero, bg=COLORS.background)
        grid.grid(row=0, column=1, sticky="nsew")
        for idx in range(2):
            grid.columnconfigure(idx, weight=1)
            grid.rowconfigure(idx, weight=1)
        self.focused_card = MetricCard(grid, self.translator.t("metrics.focused_time"))
        self.focused_card.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, SPACING.sm),
            pady=(0, SPACING.sm),
        )
        self.active_card = MetricCard(grid, self.translator.t("metrics.active_time"))
        self.active_card.grid(row=0, column=1, sticky="nsew", pady=(0, SPACING.sm))
        self.avg_card = MetricCard(grid, self.translator.t("metrics.avg_focus"))
        self.avg_card.grid(row=1, column=0, sticky="nsew", padx=(0, SPACING.sm))
        self.switch_card = MetricCard(grid, self.translator.t("metrics.context_switches"))
        self.switch_card.grid(row=1, column=1, sticky="nsew")

    def _build_secondary(self) -> None:
        lower = tk.Frame(self, bg=COLORS.background)
        lower.grid(row=3, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.lg))
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1)
        lower.rowconfigure(1, weight=1)
        self.pattern = ActivityPattern(lower, self.translator)
        self.pattern.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, SPACING.sm),
            pady=(0, SPACING.md),
        )
        self.top_apps = TopAppsList(lower, self.translator)
        self.top_apps.grid(row=0, column=1, sticky="nsew", pady=(0, SPACING.md))
        self.sessions = RecentSessionsList(lower, self.translator)
        self.sessions.grid(row=1, column=0, columnspan=2, sticky="nsew")

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        summary = snapshot.summary
        state_value, state_label, state_detail = self._current_state_text(summary)
        self.date_label.set(format_long_date(snapshot.target_date, self.translator))
        self.tracking.set_state(state_value, state_label, state_detail)
        focused_seconds = sum(s.duration_seconds for s in snapshot.sessions if s.is_focus)
        self.focused_card.set(
            format_duration(focused_seconds, self.translator),
            self.translator.plural("units.blocks", summary.focus_sessions),
        )
        self.active_card.set(
            format_duration(summary.total_active_seconds, self.translator),
            self.translator.plural("units.events", snapshot.event_count),
        )
        self.avg_card.set(
            format_duration(summary.mean_focus_block_sec, self.translator),
            self.translator.t("metrics.avg_session"),
        )
        self.switch_card.set(
            str(summary.total_context_switches),
            self.translator.plural("units.switches", summary.total_context_switches),
        )
        self.timeline.set_snapshot(snapshot)
        self.pattern.set_data(snapshot.switch_windows)
        self.top_apps.set_apps(build_top_apps(summary))
        self.sessions.set_sessions(snapshot.sessions)

    def _current_state_text(self, summary: DailySummary) -> tuple[str, str, str]:
        if summary.total_sessions == 0:
            return (
                "-",
                self.translator.t("dashboard.current_state_no_data"),
                self.translator.t("dashboard.current_state_no_data_detail"),
            )
        if summary.focus_sessions > 0:
            minutes = int(round(summary.max_focus_block_sec / 60))
            return (
                str(minutes),
                self.translator.t("dashboard.current_state_best_focus"),
                self.translator.t("dashboard.current_state_best_focus_detail"),
            )
        if summary.total_active_seconds > 0:
            return (
                format_duration(summary.total_active_seconds, self.translator),
                self.translator.t("dashboard.current_state_active"),
                self.translator.t("dashboard.current_state_active_detail"),
            )
        return (
            self.translator.t("dashboard.current_state_idle"),
            self.translator.t("dashboard.current_state_idle_label"),
            self.translator.t("dashboard.current_state_idle_detail"),
        )

    def set_tracking(self, active: bool, elapsed: str) -> None:
        self.top_status_var.set(
            self.translator.t("tracking.status.active")
            if active
            else self.translator.t("tracking.status.stopped")
        )
        self.top_status.set_active(active)
        self.tracking.set_tracking(active, elapsed)
