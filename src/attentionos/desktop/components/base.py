"""Base styled widgets for the desktop UI."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from attentionos.desktop.theme import COLORS, RADIUS, SPACING, TYPOGRAPHY


class Card(tk.Frame):
    """White surface with subtle border."""

    def __init__(self, master: tk.Misc, padding: int = SPACING.lg, **kwargs: object) -> None:
        super().__init__(
            master,
            bg=COLORS.surface,
            highlightbackground=COLORS.border,
            highlightthickness=1,
            bd=0,
            **kwargs,
        )
        self.inner = tk.Frame(self, bg=COLORS.surface)
        self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)


class TextButton(tk.Label):
    """Lightweight button with hover/pressed states."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None],
        variant: str = "secondary",
        enabled: bool = True,
        **kwargs: object,
    ) -> None:
        self.command = command
        self.variant = variant
        self.enabled = enabled
        self._pressed = False
        bg, fg = self._colors("normal")
        super().__init__(
            master,
            text=text,
            bg=bg,
            fg=fg,
            font=TYPOGRAPHY.body_semibold,
            padx=SPACING.md,
            pady=SPACING.sm,
            cursor="hand2" if enabled else "arrow",
            **kwargs,
        )
        self.bind("<Enter>", lambda _event: self._set_state("hover"))
        self.bind("<Leave>", lambda _event: self._set_state("normal"))
        self.bind("<ButtonPress-1>", lambda _event: self._set_state("pressed"))
        self.bind("<ButtonRelease-1>", self._click)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._set_state("normal")

    def _colors(self, state: str) -> tuple[str, str]:
        if not self.enabled:
            return COLORS.surface_secondary, COLORS.text_tertiary
        if self.variant == "primary":
            if state == "pressed":
                return COLORS.accent_hover, "#FFFFFF"
            if state == "hover":
                return COLORS.accent_hover, "#FFFFFF"
            return COLORS.accent, "#FFFFFF"
        if self.variant == "danger":
            if state in {"hover", "pressed"}:
                return "#FBEAEA", COLORS.danger
            return COLORS.surface_secondary, COLORS.danger
        if state in {"hover", "pressed"}:
            return COLORS.overlay, COLORS.text
        return COLORS.surface_secondary, COLORS.text

    def _set_state(self, state: str) -> None:
        bg, fg = self._colors(state)
        self.configure(bg=bg, fg=fg)

    def _click(self, _event: tk.Event) -> None:
        self._set_state("hover")
        if self.enabled:
            self.command()


class SectionHeader(tk.Frame):
    """Section title row with optional trailing content."""

    def __init__(self, master: tk.Misc, title: str, subtitle: str | None = None) -> None:
        super().__init__(master, bg=COLORS.surface)
        self.columnconfigure(0, weight=1)
        tk.Label(
            self,
            text=title,
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.section,
        ).grid(row=0, column=0, sticky="w")
        if subtitle:
            tk.Label(
                self,
                text=subtitle,
                bg=COLORS.surface,
                fg=COLORS.text_secondary,
                font=TYPOGRAPHY.caption,
            ).grid(row=1, column=0, sticky="w", pady=(SPACING.xxs, 0))


def draw_rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: int = RADIUS.md,
    **kwargs: object,
) -> int:
    """Draw a rounded rectangle polygon on a canvas."""
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)
