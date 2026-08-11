"""Tracking controls and status component."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from attentionos.desktop.components.base import Card, TextButton
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY


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
    ) -> None:
        super().__init__(master, padding=SPACING.md)
        self.on_task_change = on_task_change
        self.is_tracking = False
        self.elapsed_var = tk.StringVar(value="00:00:00")
        self.status_var = tk.StringVar(value="Ready")

        self.inner.columnconfigure(1, weight=1)
        tk.Label(
            self.inner,
            text="Current task",
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption_semibold,
        ).grid(row=0, column=0, sticky="w")

        self.task_menu = tk.OptionMenu(
            self.inner,
            task_var,
            *labels,
            command=lambda _v: on_task_change(),
        )
        self.task_menu.configure(
            bg=COLORS.surface_secondary,
            fg=COLORS.text,
            activebackground=COLORS.overlay,
            activeforeground=COLORS.text,
            highlightthickness=0,
            bd=0,
            font=TYPOGRAPHY.body_semibold,
            padx=SPACING.sm,
            pady=SPACING.xs,
            cursor="hand2",
        )
        self.task_menu["menu"].configure(font=TYPOGRAPHY.body)
        self.task_menu.grid(row=1, column=0, sticky="w", pady=(SPACING.xs, 0))

        status = tk.Frame(self.inner, bg=COLORS.surface)
        status.grid(row=0, column=1, rowspan=2, sticky="e", padx=(SPACING.md, 0))
        self.dot = tk.Canvas(
            status,
            width=14,
            height=14,
            bg=COLORS.surface,
            bd=0,
            highlightthickness=0,
        )
        self.dot.grid(row=0, column=0, padx=(0, SPACING.xs))
        self.dot_id = self.dot.create_oval(3, 3, 11, 11, fill=COLORS.idle, outline="")
        tk.Label(
            status,
            textvariable=self.status_var,
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.body_semibold,
        ).grid(row=0, column=1, sticky="w")
        tk.Label(
            status,
            textvariable=self.elapsed_var,
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption,
        ).grid(row=1, column=1, sticky="w")

        self.action_holder = tk.Frame(self.inner, bg=COLORS.surface)
        self.action_holder.grid(row=0, column=2, rowspan=2, sticky="e", padx=(SPACING.lg, 0))
        self.start_button = TextButton(
            self.action_holder,
            "Start tracking",
            on_start,
            variant="primary",
        )
        self.stop_button = TextButton(self.action_holder, "Stop", on_stop, variant="danger")
        self.check_in_button = TextButton(self.action_holder, "Check in", on_check_in)
        self.check_in_button.pack(side="left", padx=(0, SPACING.xs))
        self.start_button.pack(side="left")

    def set_tracking(self, active: bool, elapsed: str = "00:00:00") -> None:
        self.is_tracking = active
        self.elapsed_var.set(elapsed)
        self.status_var.set("Tracking" if active else "Ready")
        self.dot.itemconfigure(self.dot_id, fill=COLORS.success if active else COLORS.idle)
        self.start_button.pack_forget()
        self.stop_button.pack_forget()
        if active:
            self.stop_button.pack(side="left")
        else:
            self.start_button.pack(side="left")
