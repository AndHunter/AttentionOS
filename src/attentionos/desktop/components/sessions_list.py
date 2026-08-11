"""Recent sessions component."""

from __future__ import annotations

import tkinter as tk

from attentionos.desktop.components.base import Card
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.desktop.view_model import clean_app_name, format_duration
from attentionos.storage.schema import Session


class RecentSessionsList(Card):
    """Modern list-style replacement for raw TreeView."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=SPACING.lg)
        header = tk.Frame(self.inner, bg=COLORS.surface)
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Recent sessions",
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.section,
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="View all ->",
            bg=COLORS.surface,
            fg=COLORS.accent,
            font=TYPOGRAPHY.caption_semibold,
        ).grid(row=0, column=1, sticky="e")
        self.rows = tk.Frame(self.inner, bg=COLORS.surface)
        self.rows.pack(fill="both", expand=True, pady=(SPACING.md, 0))

    def set_sessions(self, sessions: list[Session]) -> None:
        for child in self.rows.winfo_children():
            child.destroy()
        if not sessions:
            tk.Label(
                self.rows,
                text="Sessions will appear here after tracking starts.",
                bg=COLORS.surface,
                fg=COLORS.text_secondary,
                font=TYPOGRAPHY.body,
            ).pack(anchor="w", pady=SPACING.sm)
            return

        header = tk.Frame(self.rows, bg=COLORS.surface)
        header.pack(fill="x", pady=(0, SPACING.xs))
        for idx, (text, width) in enumerate(
            [("Time", 16), ("Application", 22), ("Duration", 12), ("Task", 16)]
        ):
            tk.Label(
                header,
                text=text,
                bg=COLORS.surface,
                fg=COLORS.text_tertiary,
                font=TYPOGRAPHY.caption_semibold,
                width=width,
                anchor="w",
            ).grid(row=0, column=idx, sticky="w")

        for session in reversed(sessions[-8:]):
            self._add_row(session)

    def _add_row(self, session: Session) -> None:
        row = tk.Frame(self.rows, bg=COLORS.surface, height=42)
        row.pack(fill="x", pady=(0, 1))
        row.pack_propagate(False)
        values = [
            f"{session.ts_start.strftime('%H:%M')} - {session.ts_end.strftime('%H:%M')}",
            clean_app_name(session.process_name),
            format_duration(session.duration_seconds),
            session.task_label or "-",
        ]
        widths = [16, 22, 12, 16]
        for idx, (value, width) in enumerate(zip(values, widths, strict=True)):
            tk.Label(
                row,
                text=value,
                bg=COLORS.surface,
                fg=COLORS.text if idx == 1 else COLORS.text_secondary,
                font=TYPOGRAPHY.body_semibold if idx == 1 else TYPOGRAPHY.body,
                width=width,
                anchor="w",
            ).grid(row=0, column=idx, sticky="w", pady=SPACING.sm)
        separator = tk.Frame(self.rows, height=1, bg=COLORS.border)
        separator.pack(fill="x")

        def hover(bg: str) -> None:
            row.configure(bg=bg)
            for child in row.winfo_children():
                child.configure(bg=bg)

        row.bind("<Enter>", lambda _event: hover(COLORS.surface_hover))
        row.bind("<Leave>", lambda _event: hover(COLORS.surface))
