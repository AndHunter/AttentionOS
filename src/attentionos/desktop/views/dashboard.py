"""Main dashboard view."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from attentionos.desktop.components.app_list import TopAppsList
from attentionos.desktop.components.base import Card, TextButton
from attentionos.desktop.components.metric_card import MetricCard
from attentionos.desktop.components.sessions_list import RecentSessionsList
from attentionos.desktop.components.timeline import Timeline
from attentionos.desktop.components.tracking_control import TrackingControl
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.desktop.view_model import (
    DashboardSnapshot,
    build_top_apps,
    compute_current_state,
    format_duration,
)


class ActivityPattern(Card):
    """Simple focus/activity pattern chart from existing switch windows."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=SPACING.lg)
        tk.Label(
            self.inner,
            text="Activity pattern",
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
                text="Switching trend appears here after multiple sessions.",
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
            self.canvas.create_rectangle(
                x1,
                bottom - bar_h,
                x2,
                bottom,
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
    ) -> None:
        super().__init__(master, bg=COLORS.background)
        self.callbacks = callbacks
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        self._build_top_bar()
        self.tracking = TrackingControl(
            self,
            task_var=task_var,
            labels=task_labels,
            on_task_change=callbacks["task_change"],
            on_start=callbacks["start"],
            on_stop=callbacks["stop"],
            on_check_in=callbacks["check_in"],
        )
        self.tracking.grid(row=1, column=0, sticky="ew", padx=SPACING.xl, pady=(0, SPACING.md))
        self._build_metrics()
        self.timeline = Timeline(self, callbacks["previous_day"], callbacks["next_day"])
        self.timeline.grid(row=3, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.md))
        self._build_secondary()

    def _build_top_bar(self) -> None:
        bar = tk.Frame(self, bg=COLORS.background)
        bar.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.lg, SPACING.md))
        bar.columnconfigure(0, weight=1)
        tk.Label(
            bar,
            text="AttentionOS",
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
        self.privacy_var = tk.StringVar(value="Local only")
        tk.Label(
            right,
            textvariable=self.privacy_var,
            bg=COLORS.accent_soft,
            fg=COLORS.accent,
            font=TYPOGRAPHY.caption_semibold,
            padx=SPACING.sm,
            pady=SPACING.xs,
        ).pack(side="left", padx=(0, SPACING.xs))
        TextButton(right, "Settings", self.callbacks["diagnostics"]).pack(side="left")

    def _build_metrics(self) -> None:
        grid = tk.Frame(self, bg=COLORS.background)
        grid.grid(row=2, column=0, sticky="ew", padx=SPACING.xl, pady=(0, SPACING.md))
        grid.columnconfigure(0, weight=2, uniform="metrics")
        for idx in range(1, 5):
            grid.columnconfigure(idx, weight=1, uniform="metrics")
        self.state_card = MetricCard(grid, "Current state", large=True)
        self.state_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.sm))
        self.focused_card = MetricCard(grid, "Focused time")
        self.focused_card.grid(row=0, column=1, sticky="nsew", padx=(0, SPACING.sm))
        self.active_card = MetricCard(grid, "Active time")
        self.active_card.grid(row=0, column=2, sticky="nsew", padx=(0, SPACING.sm))
        self.avg_card = MetricCard(grid, "Avg focus")
        self.avg_card.grid(row=0, column=3, sticky="nsew", padx=(0, SPACING.sm))
        self.switch_card = MetricCard(grid, "Context switches")
        self.switch_card.grid(row=0, column=4, sticky="nsew")

    def _build_secondary(self) -> None:
        lower = tk.Frame(self, bg=COLORS.background)
        lower.grid(row=4, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.lg))
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1)
        lower.rowconfigure(1, weight=1)
        self.pattern = ActivityPattern(lower)
        self.pattern.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, SPACING.sm),
            pady=(0, SPACING.md),
        )
        self.top_apps = TopAppsList(lower)
        self.top_apps.grid(row=0, column=1, sticky="nsew", pady=(0, SPACING.md))
        self.sessions = RecentSessionsList(lower)
        self.sessions.grid(row=1, column=0, columnspan=2, sticky="nsew")

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        summary = snapshot.summary
        state = compute_current_state(summary)
        self.date_label.set(snapshot.target_date.strftime("%A, %B %d, %Y"))
        self.state_card.set(state.value, f"{state.label}. {state.detail}")
        focused_seconds = sum(s.duration_seconds for s in snapshot.sessions if s.is_focus)
        self.focused_card.set(
            format_duration(focused_seconds),
            f"{summary.focus_sessions} blocks",
        )
        self.active_card.set(
            format_duration(summary.total_active_seconds),
            f"{snapshot.event_count} events",
        )
        self.avg_card.set(format_duration(summary.mean_focus_block_sec), "Avg session")
        self.switch_card.set(str(summary.total_context_switches), "Switches")
        self.timeline.set_snapshot(snapshot)
        self.pattern.set_data(snapshot.switch_windows)
        self.top_apps.set_apps(build_top_apps(summary))
        self.sessions.set_sessions(snapshot.sessions)

    def set_tracking(self, active: bool, elapsed: str) -> None:
        self.tracking.set_tracking(active, elapsed)
