"""Metric cards for the dashboard."""

from __future__ import annotations

import tkinter as tk

from attentionos.desktop.components.base import Card
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY


class MetricCard(Card):
    """Compact dashboard metric card."""

    def __init__(self, master: tk.Misc, label: str, large: bool = False) -> None:
        super().__init__(master, padding=SPACING.lg, variant="soft")
        self.value_var = tk.StringVar(value="0")
        self.label_var = tk.StringVar(value=label)
        self.detail_var = tk.StringVar(value="")

        tk.Label(
            self.inner,
            textvariable=self.label_var,
            bg=COLORS.surface_secondary,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption_semibold,
        ).pack(anchor="w")
        tk.Label(
            self.inner,
            textvariable=self.value_var,
            bg=COLORS.surface_secondary,
            fg=COLORS.text,
            font=TYPOGRAPHY.display if large else TYPOGRAPHY.metric,
        ).pack(anchor="w", pady=(SPACING.xs, 0))
        tk.Label(
            self.inner,
            textvariable=self.detail_var,
            bg=COLORS.surface_secondary,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption,
        ).pack(anchor="w", pady=(SPACING.xs, 0))

    def set(self, value: str, detail: str = "") -> None:
        self.value_var.set(value)
        self.detail_var.set(detail)
