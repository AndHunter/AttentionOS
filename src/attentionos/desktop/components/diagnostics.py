"""Developer diagnostics drawer."""

from __future__ import annotations

import tkinter as tk

from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY


class DiagnosticsDrawer(tk.Toplevel):
    """Small diagnostics window for system telemetry details."""

    def __init__(self, master: tk.Misc, db_path: str) -> None:
        super().__init__(master)
        self.title("Developer diagnostics")
        self.configure(bg=COLORS.background)
        self.resizable(False, False)
        self.vars = {
            "Events": tk.StringVar(value="0"),
            "Hooks": tk.StringVar(value="off"),
            "Keys": tk.StringVar(value="0"),
            "Mouse": tk.StringVar(value="0"),
            "Idle": tk.StringVar(value="0s"),
            "SQLite": tk.StringVar(value=db_path),
        }
        shell = tk.Frame(
            self,
            bg=COLORS.surface,
            highlightbackground=COLORS.border,
            highlightthickness=1,
        )
        shell.pack(fill="both", expand=True, padx=SPACING.lg, pady=SPACING.lg)
        tk.Label(
            shell,
            text="Developer diagnostics",
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.section,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=SPACING.lg, pady=SPACING.lg)
        for row, (label, value) in enumerate(self.vars.items(), 1):
            tk.Label(
                shell,
                text=label,
                bg=COLORS.surface,
                fg=COLORS.text_secondary,
                font=TYPOGRAPHY.caption_semibold,
            ).grid(row=row, column=0, sticky="nw", padx=SPACING.lg, pady=(0, SPACING.sm))
            tk.Label(
                shell,
                textvariable=value,
                bg=COLORS.surface,
                fg=COLORS.text,
                font=TYPOGRAPHY.caption,
                wraplength=360,
                justify="left",
            ).grid(row=row, column=1, sticky="w", padx=(0, SPACING.lg), pady=(0, SPACING.sm))

    def set_stats(self, stats: dict[str, float | int]) -> None:
        self.vars["Events"].set(str(stats.get("total_events", 0)))
        self.vars["Hooks"].set("on" if stats.get("input_hooks_running") else "off")
        self.vars["Keys"].set(str(stats.get("last_keyboard_events", 0)))
        self.vars["Mouse"].set(str(stats.get("last_mouse_events", 0)))
        self.vars["Idle"].set(f"{float(stats.get('last_idle_seconds', 0)):.0f}s")
