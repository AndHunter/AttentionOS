"""Ranked app list component."""

from __future__ import annotations

import tkinter as tk

from attentionos.desktop.components.base import Card
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.desktop.view_model import TopApp, format_duration
from attentionos.localization import Translator


class TopAppsList(Card):
    """Compact ranked list of top applications."""

    def __init__(self, master: tk.Misc, translator: Translator) -> None:
        super().__init__(master, padding=SPACING.lg)
        self.translator = translator
        self.rows = tk.Frame(self.inner, bg=COLORS.surface)
        tk.Label(
            self.inner,
            text=translator.t("dashboard.top_apps"),
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.section,
        ).pack(anchor="w")
        self.rows.pack(fill="both", expand=True, pady=(SPACING.md, 0))

    def set_apps(self, apps: list[TopApp]) -> None:
        for child in self.rows.winfo_children():
            child.destroy()
        if not apps:
            tk.Label(
                self.rows,
                text=self.translator.t("metrics.not_enough_data"),
                bg=COLORS.surface,
                fg=COLORS.text_secondary,
                font=TYPOGRAPHY.body,
            ).pack(anchor="w", pady=SPACING.sm)
            return

        for idx, app in enumerate(apps[:5], 1):
            row = tk.Frame(self.rows, bg=COLORS.surface)
            row.pack(fill="x", pady=(0, SPACING.sm))
            row.columnconfigure(1, weight=1)
            tk.Label(
                row,
                text=f"{idx}.",
                bg=COLORS.surface,
                fg=COLORS.text_tertiary,
                font=TYPOGRAPHY.caption_semibold,
                width=3,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            tk.Label(
                row,
                text=app.name,
                bg=COLORS.surface,
                fg=COLORS.text,
                font=TYPOGRAPHY.body_semibold,
            ).grid(row=0, column=1, sticky="w")
            tk.Label(
                row,
                text=f"{format_duration(app.seconds)}  {app.percent:.0f}%",
                bg=COLORS.surface,
                fg=COLORS.text_secondary,
                font=TYPOGRAPHY.caption,
            ).grid(row=0, column=2, sticky="e")

            bar = tk.Canvas(row, height=7, bg=COLORS.surface, bd=0, highlightthickness=0)
            bar.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(SPACING.xs, 0))
            bar.bind(
                "<Configure>",
                lambda event, value=app.percent: self._draw_bar(event.widget, value),
            )

    @staticmethod
    def _draw_bar(canvas: tk.Canvas, percent: float) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        canvas.create_rectangle(0, 0, width, 7, fill=COLORS.surface_secondary, outline="")
        canvas.create_rectangle(0, 0, width * (percent / 100), 7, fill=COLORS.accent, outline="")
