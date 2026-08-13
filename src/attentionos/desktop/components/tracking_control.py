"""Tracking controls and status component."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from attentionos.desktop.components.base import Card, Pill, TextButton
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.localization import Translator


class TrackingControl(Card):
    """Current task selector and primary tracking CTA."""

    def __init__(
        self,
        master: tk.Misc,
        task_var: tk.StringVar,
        labels: list[str],
        on_task_change: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_check_in: Callable[[], None],
        translator: Translator,
    ) -> None:
        super().__init__(master, padding=SPACING.xl, variant="hero")
        self.on_task_change = on_task_change
        self.translator = translator
        self.is_tracking = False
        self.elapsed_var = tk.StringVar(value="00:00:00")
        self.status_var = tk.StringVar(value=translator.t("tracking.status.stopped"))
        self.state_value_var = tk.StringVar(value="--")
        self.state_label_var = tk.StringVar(value=translator.t("metrics.current_state"))
        self.state_detail_var = tk.StringVar(value=translator.t("metrics.not_enough_data"))

        self.inner.columnconfigure(0, weight=1)
        self.inner.rowconfigure(3, weight=1)

        eyebrow = tk.Frame(self.inner, bg=COLORS.surface)
        eyebrow.grid(row=0, column=0, sticky="ew")
        eyebrow.columnconfigure(0, weight=1)
        tk.Label(
            eyebrow,
            text=translator.t("dashboard.current_state_eyebrow").upper(),
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption_semibold,
        ).grid(row=0, column=0, sticky="w")
        self.status_pill = Pill(eyebrow, self.status_var)
        self.status_pill.grid(row=0, column=1, sticky="e")

        tk.Label(
            self.inner,
            textvariable=self.state_value_var,
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.display,
        ).grid(row=1, column=0, sticky="w", pady=(SPACING.lg, 0))
        tk.Label(
            self.inner,
            textvariable=self.state_label_var,
            bg=COLORS.surface,
            fg=COLORS.accent,
            font=TYPOGRAPHY.section,
        ).grid(row=2, column=0, sticky="w")
        tk.Label(
            self.inner,
            textvariable=self.state_detail_var,
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.body,
            wraplength=420,
            justify="left",
        ).grid(row=3, column=0, sticky="nw", pady=(SPACING.xs, SPACING.lg))

        control_row = tk.Frame(self.inner, bg=COLORS.surface)
        control_row.grid(row=4, column=0, sticky="ew")
        control_row.columnconfigure(0, weight=1)
        tk.Label(
            control_row,
            text=translator.t("tracking.current_task"),
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption_semibold,
        ).grid(row=0, column=0, sticky="w")
        task_shell = tk.Frame(
            control_row,
            bg=COLORS.surface_secondary,
            highlightbackground=COLORS.border,
            highlightthickness=1,
        )
        task_shell.grid(row=1, column=0, sticky="ew", pady=(SPACING.xs, 0))
        self.task_menu = tk.OptionMenu(
            task_shell,
            task_var,
            *labels,
            command=lambda _v: on_task_change(),
        )
        self.task_menu.configure(
            bg=COLORS.surface_secondary,
            fg=COLORS.text,
            activebackground=COLORS.surface_hover,
            activeforeground=COLORS.text,
            highlightthickness=0,
            bd=0,
            font=TYPOGRAPHY.body_semibold,
            padx=SPACING.sm,
            pady=SPACING.xs,
            cursor="hand2",
        )
        self.task_menu["menu"].configure(
            bg=COLORS.surface_secondary,
            fg=COLORS.text,
            activebackground=COLORS.surface_hover,
            activeforeground=COLORS.text,
            font=TYPOGRAPHY.body,
        )
        self.task_menu.pack(fill="x")
        tk.Label(
            control_row,
            textvariable=self.elapsed_var,
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.metric,
        ).grid(row=1, column=1, sticky="e", padx=(SPACING.md, 0))

        self.action_holder = tk.Frame(self.inner, bg=COLORS.surface)
        self.action_holder.grid(row=5, column=0, sticky="ew", pady=(SPACING.lg, 0))
        self.start_button = TextButton(
            self.action_holder,
            translator.t("tracking.start"),
            on_start,
            variant="primary",
        )
        self.stop_button = TextButton(
            self.action_holder,
            translator.t("tracking.stop"),
            on_stop,
            variant="danger",
        )
        self.check_in_button = TextButton(
            self.action_holder,
            translator.t("tracking.check_in"),
            on_check_in,
        )
        self.check_in_button.pack(side="left", padx=(0, SPACING.xs))
        self.start_button.pack(side="right")

    def set_state(self, value: str, label: str, detail: str) -> None:
        self.state_value_var.set(value)
        self.state_label_var.set(label)
        self.state_detail_var.set(detail)

    def set_tracking(self, active: bool, elapsed: str = "00:00:00") -> None:
        self.is_tracking = active
        self.elapsed_var.set(elapsed)
        self.status_var.set(
            self.translator.t("tracking.status.active")
            if active
            else self.translator.t("tracking.status.stopped")
        )
        self.status_pill.set_active(active)
        self.start_button.pack_forget()
        self.stop_button.pack_forget()
        if active:
            self.stop_button.pack(side="right")
        else:
            self.start_button.pack(side="right")
