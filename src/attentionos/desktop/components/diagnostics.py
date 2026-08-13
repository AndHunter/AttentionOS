"""Developer diagnostics drawer."""

from __future__ import annotations

import tkinter as tk

from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.localization import Translator


class DiagnosticsDrawer(tk.Toplevel):
    """Small diagnostics window for system telemetry details."""

    def __init__(self, master: tk.Misc, db_path: str, translator: Translator) -> None:
        super().__init__(master)
        self.translator = translator
        self.title(translator.t("diagnostics.title"))
        self.configure(bg=COLORS.background)
        self.resizable(False, False)
        self.vars = {
            "diagnostics.events": tk.StringVar(value="0"),
            "diagnostics.hooks": tk.StringVar(value=translator.t("diagnostics.off")),
            "diagnostics.keys": tk.StringVar(value="0"),
            "diagnostics.mouse": tk.StringVar(value="0"),
            "diagnostics.idle": tk.StringVar(value=translator.t("diagnostics.seconds", count=0)),
            "diagnostics.sqlite": tk.StringVar(value=db_path),
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
            text=translator.t("diagnostics.title"),
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.section,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=SPACING.lg, pady=SPACING.lg)
        for row, (label, value) in enumerate(self.vars.items(), 1):
            tk.Label(
                shell,
                text=translator.t(label),
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
        self.vars["diagnostics.events"].set(str(stats.get("total_events", 0)))
        self.vars["diagnostics.hooks"].set(
            self.translator.t("diagnostics.on")
            if stats.get("input_hooks_running")
            else self.translator.t("diagnostics.off")
        )
        self.vars["diagnostics.keys"].set(str(stats.get("last_keyboard_events", 0)))
        self.vars["diagnostics.mouse"].set(str(stats.get("last_mouse_events", 0)))
        idle = int(round(float(stats.get("last_idle_seconds", 0))))
        self.vars["diagnostics.idle"].set(self.translator.t("diagnostics.seconds", count=idle))
