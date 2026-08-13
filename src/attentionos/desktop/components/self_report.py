"""Self-report modal for manual check-ins."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from attentionos.desktop.components.base import TextButton
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.localization import Translator


class RatingGroup(tk.Frame):
    """Segmented 1-5 rating control."""

    def __init__(self, master: tk.Misc, label: str, initial: int = 3) -> None:
        super().__init__(master, bg=COLORS.surface)
        self.value = tk.IntVar(value=initial)
        self.buttons: list[tk.Label] = []
        tk.Label(
            self,
            text=label,
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.body_semibold,
        ).pack(anchor="w", pady=(0, SPACING.xs))
        row = tk.Frame(self, bg=COLORS.surface)
        row.pack(anchor="w")
        for idx in range(1, 6):
            button = tk.Label(
                row,
                text=str(idx),
                width=4,
                bg=COLORS.surface_secondary,
                fg=COLORS.text,
                font=TYPOGRAPHY.body_semibold,
                padx=SPACING.xs,
                pady=SPACING.xs,
                cursor="hand2",
            )
            button.pack(side="left", padx=(0, SPACING.xs))
            button.bind("<Button-1>", lambda _event, value=idx: self.set(value))
            self.buttons.append(button)
        self.set(initial)

    def set(self, value: int) -> None:
        self.value.set(value)
        for idx, button in enumerate(self.buttons, 1):
            selected = idx == value
            button.configure(
                bg=COLORS.accent if selected else COLORS.surface_secondary,
                fg=COLORS.accent_text if selected else COLORS.text,
            )


class SelfReportDialog(tk.Toplevel):
    """Small modal dialog for check-ins."""

    def __init__(
        self,
        master: tk.Misc,
        on_save: Callable[[int, int, int | None, str | None], None],
        translator: Translator,
    ) -> None:
        super().__init__(master)
        self.on_save = on_save
        self.title(translator.t("tracking.check_in"))
        self.configure(bg=COLORS.background)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        shell = tk.Frame(
            self,
            bg=COLORS.surface,
            highlightbackground=COLORS.border,
            highlightthickness=1,
        )
        shell.pack(fill="both", expand=True, padx=SPACING.lg, pady=SPACING.lg)
        shell.columnconfigure(0, weight=1)

        tk.Label(
            shell,
            text=translator.t("self_report.title"),
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.page_title,
        ).grid(row=0, column=0, sticky="w", padx=SPACING.lg, pady=(SPACING.lg, SPACING.xs))
        tk.Label(
            shell,
            text=translator.t("self_report.subtitle"),
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.body,
        ).grid(row=1, column=0, sticky="w", padx=SPACING.lg)

        self.effectiveness = RatingGroup(shell, translator.t("self_report.effectiveness"), 3)
        self.effectiveness.grid(row=2, column=0, sticky="w", padx=SPACING.lg, pady=(SPACING.lg, 0))
        self.fatigue = RatingGroup(shell, translator.t("self_report.fatigue"), 2)
        self.fatigue.grid(row=3, column=0, sticky="w", padx=SPACING.lg, pady=(SPACING.md, 0))
        self.difficulty = RatingGroup(shell, translator.t("self_report.difficulty"), 3)
        self.difficulty.grid(row=4, column=0, sticky="w", padx=SPACING.lg, pady=(SPACING.md, 0))

        tk.Label(
            shell,
            text=translator.t("self_report.note"),
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.body_semibold,
        ).grid(row=5, column=0, sticky="w", padx=SPACING.lg, pady=(SPACING.lg, SPACING.xs))
        self.note = tk.Entry(
            shell,
            bg=COLORS.surface_secondary,
            fg=COLORS.text,
            insertbackground=COLORS.text,
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.accent,
            highlightthickness=1,
            relief="flat",
            font=TYPOGRAPHY.body,
            width=48,
        )
        self.note.grid(row=6, column=0, sticky="ew", padx=SPACING.lg, ipady=SPACING.xs)

        actions = tk.Frame(shell, bg=COLORS.surface)
        actions.grid(row=7, column=0, sticky="e", padx=SPACING.lg, pady=SPACING.lg)
        TextButton(actions, translator.t("self_report.skip"), self.destroy).pack(
            side="left", padx=(0, SPACING.xs)
        )
        TextButton(
            actions,
            translator.t("self_report.save"),
            self._save,
            variant="primary",
        ).pack(side="left")

        self.update_idletasks()
        x = master.winfo_rootx() + max((master.winfo_width() - self.winfo_width()) // 2, 0)
        y = master.winfo_rooty() + max((master.winfo_height() - self.winfo_height()) // 2, 0)
        self.geometry(f"+{x}+{y}")

    def _save(self) -> None:
        note = self.note.get().strip() or None
        self.on_save(
            self.effectiveness.value.get(),
            self.fatigue.value.get(),
            self.difficulty.value.get(),
            note,
        )
        self.destroy()
