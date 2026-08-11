"""Settings window for runtime preferences, privacy controls, and model status."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from attentionos.desktop.components.base import TextButton
from attentionos.desktop.theme import COLORS, SPACING, TYPOGRAPHY
from attentionos.localization import Translator
from attentionos.settings import RuntimeSettings


class SettingsWindow(tk.Toplevel):
    """Product settings page."""

    def __init__(
        self,
        master: tk.Misc,
        settings: RuntimeSettings,
        translator: Translator,
        db_path: str,
        model_counts: dict[str, int],
        callbacks: dict[str, Callable[..., None]],
    ) -> None:
        super().__init__(master)
        self.settings = settings.model_copy(deep=True)
        self.translator = translator
        self.callbacks = callbacks
        self.title(translator.t("settings.title"))
        self.configure(bg=COLORS.background)
        self.geometry("760x680")
        self.minsize(720, 620)
        self.transient(master)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        tk.Label(
            self,
            text=translator.t("settings.title"),
            bg=COLORS.background,
            fg=COLORS.text,
            font=TYPOGRAPHY.page_title,
        ).grid(row=0, column=0, sticky="w", padx=SPACING.xl, pady=(SPACING.lg, SPACING.md))

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=SPACING.xl)
        self._build_general(notebook)
        self._build_tracking(notebook)
        self._build_notifications(notebook)
        self._build_privacy(notebook, db_path)
        self._build_model(notebook, model_counts)

        actions = tk.Frame(self, bg=COLORS.background)
        actions.grid(row=2, column=0, sticky="e", padx=SPACING.xl, pady=SPACING.lg)
        TextButton(actions, translator.t("settings.close"), self.destroy).pack(
            side="left", padx=(0, SPACING.xs)
        )
        TextButton(actions, translator.t("settings.save"), self._save, variant="primary").pack(
            side="left"
        )

    def _section(self, notebook: ttk.Notebook, key: str) -> tk.Frame:
        frame = tk.Frame(notebook, bg=COLORS.surface, padx=SPACING.lg, pady=SPACING.lg)
        notebook.add(frame, text=self.translator.t(key))
        frame.columnconfigure(1, weight=1)
        return frame

    def _build_general(self, notebook: ttk.Notebook) -> None:
        frame = self._section(notebook, "settings.general")
        self.language = tk.StringVar(value=self.settings.preferences.language)
        self.theme = tk.StringVar(value=self.settings.preferences.theme)
        row = 0
        self._option(frame, row, "settings.language", self.language, ["system", "en", "ru"])
        row += 1
        self._option(frame, row, "settings.theme", self.theme, ["system", "light", "dark"])
        row += 1
        self.launch = self._check(
            frame,
            row,
            "settings.launch_on_startup",
            self.settings.preferences.launch_on_startup,
        )
        row += 1
        self.tray = self._check(
            frame,
            row,
            "settings.minimize_to_tray",
            self.settings.preferences.minimize_to_tray,
        )
        row += 1
        self.start_minimized = self._check(
            frame,
            row,
            "settings.start_minimized",
            self.settings.preferences.start_minimized,
        )
        row += 1
        tk.Label(
            frame,
            text=self.translator.t("settings.apply_restart"),
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(SPACING.md, 0))

    def _build_tracking(self, notebook: ttk.Notebook) -> None:
        frame = self._section(notebook, "settings.tracking")
        self.idle_threshold = tk.IntVar(value=self.settings.tracking.idle_threshold_minutes)
        self.track_active = self._check(
            frame,
            1,
            "settings.track_active_window",
            self.settings.tracking.track_active_window,
        )
        self.track_titles = self._check(
            frame,
            2,
            "settings.track_window_titles",
            self.settings.tracking.track_window_titles,
        )
        self.track_keyboard = self._check(
            frame,
            3,
            "settings.track_keyboard",
            self.settings.tracking.track_keyboard_activity,
        )
        self.track_mouse = self._check(
            frame,
            4,
            "settings.track_mouse",
            self.settings.tracking.track_mouse_activity,
        )
        self._label(frame, 0, "settings.idle_threshold")
        tk.Spinbox(
            frame,
            from_=1,
            to=30,
            textvariable=self.idle_threshold,
            width=8,
            font=TYPOGRAPHY.body,
        ).grid(row=0, column=1, sticky="w", pady=SPACING.xs)
        self.excluded_entry = tk.StringVar()
        self.excluded = tk.Listbox(frame, height=7, font=TYPOGRAPHY.body)
        self.excluded.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(SPACING.sm, 0))
        for item in self.settings.tracking.excluded_applications:
            self.excluded.insert("end", item)
        self._label(frame, 5, "settings.excluded_apps")
        entry_row = tk.Frame(frame, bg=COLORS.surface)
        entry_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=SPACING.sm)
        entry_row.columnconfigure(0, weight=1)
        tk.Entry(entry_row, textvariable=self.excluded_entry, font=TYPOGRAPHY.body).grid(
            row=0, column=0, sticky="ew", ipady=SPACING.xs
        )
        TextButton(entry_row, self.translator.t("settings.add_app"), self._add_excluded).grid(
            row=0, column=1, padx=SPACING.xs
        )
        TextButton(
            entry_row,
            self.translator.t("settings.remove_selected"),
            self._remove_excluded,
        ).grid(row=0, column=2)

    def _build_notifications(self, notebook: ttk.Notebook) -> None:
        frame = self._section(notebook, "settings.notifications")
        self.breaks = self._check(
            frame,
            0,
            "settings.break_recommendations",
            self.settings.notifications.break_recommendations,
        )
        self.performance_warnings = self._check(
            frame,
            1,
            "settings.performance_warnings",
            self.settings.notifications.performance_warnings,
        )
        self.interval = tk.StringVar(
            value=str(self.settings.notifications.minimum_interval_minutes)
        )
        self._option(
            frame,
            2,
            "settings.notification_interval",
            self.interval,
            ["15", "30", "45", "60"],
        )
        self.dnd_start = tk.StringVar(value=self.settings.notifications.do_not_disturb_start)
        self.dnd_end = tk.StringVar(value=self.settings.notifications.do_not_disturb_end)
        self._entry(frame, 3, "settings.dnd_start", self.dnd_start)
        self._entry(frame, 4, "settings.dnd_end", self.dnd_end)

    def _build_privacy(self, notebook: ttk.Notebook, db_path: str) -> None:
        frame = self._section(notebook, "settings.privacy")
        tk.Label(
            frame,
            text=self.translator.t("settings.stored_locally"),
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.body_semibold,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self._label(frame, 1, "settings.database_path")
        tk.Label(
            frame,
            text=db_path,
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption,
            wraplength=520,
            justify="left",
        ).grid(row=1, column=1, sticky="w")
        buttons = [
            ("settings.export_data", "export"),
            ("settings.delete_telemetry", "delete_telemetry"),
            ("settings.delete_self_reports", "delete_reports"),
            ("settings.delete_model", "delete_model"),
            ("settings.delete_all", "delete_all"),
        ]
        for idx, (label, action) in enumerate(buttons, 2):
            TextButton(
                frame,
                self.translator.t(label),
                lambda name=action: self.callbacks[name](),
                variant="danger" if action.startswith("delete") else "default",
            ).grid(row=idx, column=0, sticky="w", pady=SPACING.xs)
        tk.Label(
            frame,
            text=self.translator.t("settings.never_records"),
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.body,
            wraplength=620,
            justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(SPACING.lg, 0))

    def _build_model(self, notebook: ttk.Notebook, counts: dict[str, int]) -> None:
        frame = self._section(notebook, "settings.model")
        rows = [
            (
                self.translator.t("settings.personal_model"),
                self.translator.t("settings.collecting_data"),
            ),
            (self.translator.t("settings.telemetry_windows"), str(counts.get("events", 0))),
            (self.translator.t("settings.self_reports"), str(counts.get("reports", 0))),
        ]
        for row, (label, value) in enumerate(rows):
            tk.Label(
                frame,
                text=label,
                bg=COLORS.surface,
                fg=COLORS.text,
                font=TYPOGRAPHY.body_semibold,
            ).grid(row=row, column=0, sticky="w", pady=SPACING.xs)
            tk.Label(
                frame,
                text=value,
                bg=COLORS.surface,
                fg=COLORS.text_secondary,
                font=TYPOGRAPHY.body,
            ).grid(row=row, column=1, sticky="w", pady=SPACING.xs)
        train_enabled = counts.get("reports", 0) >= counts.get("min_training_samples", 30)
        TextButton(
            frame,
            self.translator.t("settings.train"),
            lambda: None,
            enabled=train_enabled,
        ).grid(row=4, column=0, sticky="w", pady=(SPACING.lg, 0))
        tk.Label(
            frame,
            text=f"{counts.get('reports', 0)}/{counts.get('min_training_samples', 30)}",
            bg=COLORS.surface,
            fg=COLORS.text_secondary,
            font=TYPOGRAPHY.caption,
        ).grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(SPACING.sm, 0),
        )
        TextButton(
            frame,
            self.translator.t("settings.reset_model"),
            self.callbacks["delete_model"],
        ).grid(
            row=4, column=1, sticky="w", pady=(SPACING.lg, 0)
        )

    def _label(self, frame: tk.Frame, row: int, key: str) -> None:
        tk.Label(
            frame,
            text=self.translator.t(key),
            bg=COLORS.surface,
            fg=COLORS.text,
            font=TYPOGRAPHY.body_semibold,
        ).grid(row=row, column=0, sticky="w", pady=SPACING.xs)

    def _entry(self, frame: tk.Frame, row: int, key: str, var: tk.StringVar) -> None:
        self._label(frame, row, key)
        tk.Entry(frame, textvariable=var, font=TYPOGRAPHY.body).grid(
            row=row, column=1, sticky="w", pady=SPACING.xs, ipady=SPACING.xs
        )

    def _option(
        self,
        frame: tk.Frame,
        row: int,
        key: str,
        var: tk.StringVar,
        values: list[str],
    ) -> None:
        self._label(frame, row, key)
        tk.OptionMenu(frame, var, *values).grid(row=row, column=1, sticky="w", pady=SPACING.xs)

    def _check(self, frame: tk.Frame, row: int, key: str, initial: bool) -> tk.BooleanVar:
        var = tk.BooleanVar(value=initial)
        tk.Checkbutton(
            frame,
            text=self.translator.t(key),
            variable=var,
            bg=COLORS.surface,
            fg=COLORS.text,
            activebackground=COLORS.surface,
            font=TYPOGRAPHY.body,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=SPACING.xs)
        return var

    def _add_excluded(self) -> None:
        value = self.excluded_entry.get().strip()
        if value:
            self.excluded.insert("end", value)
            self.excluded_entry.set("")

    def _remove_excluded(self) -> None:
        for index in reversed(self.excluded.curselection()):
            self.excluded.delete(index)

    def _save(self) -> None:
        self.settings.preferences.language = self.language.get()  # type: ignore[assignment]
        self.settings.preferences.theme = self.theme.get()  # type: ignore[assignment]
        self.settings.preferences.launch_on_startup = self.launch.get()
        self.settings.preferences.minimize_to_tray = self.tray.get()
        self.settings.preferences.start_minimized = self.start_minimized.get()
        self.settings.tracking.idle_threshold_minutes = self.idle_threshold.get()
        self.settings.tracking.track_active_window = self.track_active.get()
        self.settings.tracking.track_window_titles = self.track_titles.get()
        self.settings.tracking.track_keyboard_activity = self.track_keyboard.get()
        self.settings.tracking.track_mouse_activity = self.track_mouse.get()
        self.settings.tracking.excluded_applications = [
            self.excluded.get(index) for index in range(self.excluded.size())
        ]
        self.settings.notifications.break_recommendations = self.breaks.get()
        self.settings.notifications.performance_warnings = self.performance_warnings.get()
        self.settings.notifications.minimum_interval_minutes = int(self.interval.get())
        self.settings.notifications.do_not_disturb_start = self.dnd_start.get()
        self.settings.notifications.do_not_disturb_end = self.dnd_end.get()
        self.callbacks["save"](self.settings)
        self.destroy()
