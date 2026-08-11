"""Timeline visualization component."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import datetime

from attentionos.desktop.components.base import Card, TextButton, draw_rounded_rect
from attentionos.desktop.theme import APP_COLORS, COLORS, RADIUS, SPACING, TYPOGRAPHY
from attentionos.desktop.view_model import DashboardSnapshot, clean_app_name, format_duration


class Timeline(Card):
    """Large workday timeline with hover tooltip."""

    def __init__(
        self,
        master: tk.Misc,
        on_previous_day: Callable[[], None],
        on_next_day: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=SPACING.lg)
        self.snapshot: DashboardSnapshot | None = None
        self._segments: list[tuple[int, object]] = []
        self.date_var = tk.StringVar(value="Today")
        self.tooltip = tk.Label(
            self,
            bg="#20242B",
            fg="#FFFFFF",
            font=TYPOGRAPHY.caption,
            padx=SPACING.sm,
            pady=SPACING.xs,
            justify="left",
        )

        header = tk.Frame(self.inner, bg=COLORS.surface)
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Timeline",
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.section,
        ).grid(row=0, column=0, sticky="w")
        nav = tk.Frame(header, bg=COLORS.surface)
        nav.grid(row=0, column=1, sticky="e")
        TextButton(nav, "<", on_previous_day).pack(side="left")
        tk.Label(
            nav,
            textvariable=self.date_var,
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.body_semibold,
            padx=SPACING.sm,
        ).pack(side="left")
        TextButton(nav, ">", on_next_day).pack(side="left")

        self.canvas = tk.Canvas(
            self.inner,
            height=230,
            bg=COLORS.surface,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True, pady=(SPACING.md, 0))
        self.canvas.bind("<Configure>", lambda _event: self.draw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _event: self.tooltip.place_forget())

    def set_snapshot(self, snapshot: DashboardSnapshot) -> None:
        self.snapshot = snapshot
        label = snapshot.target_date.strftime("%b %d")
        self.date_var.set(f"Today, {label}" if snapshot.is_today else label)
        self.draw()

    def draw(self) -> None:
        self.canvas.delete("all")
        self._segments.clear()
        snapshot = self.snapshot
        width = max(self.canvas.winfo_width(), 700)
        left = 56
        right = width - 28
        top = 78
        height = 48

        tk_font = TYPOGRAPHY.caption
        self.canvas.create_text(
            left,
            22,
            text="09:00 - 18:00 workday",
            anchor="w",
            fill=COLORS.text_secondary,
            font=tk_font,
        )
        draw_rounded_rect(
            self.canvas,
            left,
            top,
            right,
            top + height,
            radius=RADIUS.md,
            fill=COLORS.surface_secondary,
            outline="",
        )

        for hour in range(9, 19):
            x = left + (right - left) * ((hour - 9) / 9)
            self.canvas.create_line(x, top - 12, x, top + height + 12, fill=COLORS.border)
            self.canvas.create_text(
                x,
                top + height + 30,
                text=f"{hour:02d}:00",
                fill=COLORS.text_tertiary,
                font=tk_font,
            )

        if snapshot is None or not snapshot.sessions:
            self._draw_empty(width, left, right, top, height)
            return

        color_map: dict[str, str] = {}
        day_start = datetime.combine(snapshot.target_date, datetime.min.time()).replace(hour=9)
        work_seconds = 9 * 60 * 60
        for session in snapshot.sessions:
            start = (session.ts_start.replace(tzinfo=None) - day_start).total_seconds()
            end = (session.ts_end.replace(tzinfo=None) - day_start).total_seconds()
            if end < 0 or start > work_seconds:
                continue
            start = max(start, 0)
            end = min(max(end, start + 1), work_seconds)
            x1 = left + (right - left) * (start / work_seconds)
            x2 = left + (right - left) * (end / work_seconds)
            if x2 - x1 < 3:
                x2 = x1 + 3
            color = COLORS.idle if session.is_idle else self._color(session.process_name, color_map)
            segment_id = draw_rounded_rect(
                self.canvas,
                x1,
                top,
                x2,
                top + height,
                radius=RADIUS.sm,
                fill=color,
                outline="",
            )
            self._segments.append((segment_id, session))
            if session.is_focus:
                self.canvas.create_rectangle(
                    x1,
                    top - 7,
                    x2,
                    top - 3,
                    fill=COLORS.accent,
                    outline="",
                )

    def _draw_empty(self, width: int, left: int, right: int, top: int, height: int) -> None:
        self.canvas.create_text(
            width / 2,
            top + height / 2 - 8,
            text="No focus data yet",
            fill=COLORS.text,
            font=TYPOGRAPHY.body_semibold,
        )
        self.canvas.create_text(
            width / 2,
            top + height / 2 + 16,
            text="Start tracking and AttentionOS will build your first daily timeline.",
            fill=COLORS.text_secondary,
            font=TYPOGRAPHY.caption,
        )

    def _on_motion(self, event: tk.Event) -> None:
        hit = self.canvas.find_closest(event.x, event.y)
        if not hit:
            self.tooltip.place_forget()
            return
        for segment_id, session in self._segments:
            if segment_id == hit[0]:
                text = (
                    f"{session.ts_start.strftime('%H:%M')}-{session.ts_end.strftime('%H:%M')}\n"
                    f"{clean_app_name(session.process_name)}\n"
                    f"{format_duration(session.duration_seconds)}"
                )
                if session.task_label:
                    text += f"\nTask: {session.task_label}"
                self.tooltip.configure(text=text)
                self.tooltip.place(
                    x=event.x_root - self.winfo_rootx() + 12,
                    y=event.y_root - self.winfo_rooty() + 12,
                )
                return
        self.tooltip.place_forget()

    @staticmethod
    def _color(name: str, color_map: dict[str, str]) -> str:
        if name not in color_map:
            color_map[name] = APP_COLORS[len(color_map) % len(APP_COLORS)]
        return color_map[name]
