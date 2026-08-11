"""Small JSON translation layer for desktop user-facing strings."""

from __future__ import annotations

import json
import locale
from importlib import resources
from typing import Literal

Language = Literal["system", "en", "ru"]


def detect_system_language() -> str:
    """Return supported language from OS locale."""
    lang, _encoding = locale.getlocale()
    if lang and lang.lower().startswith("ru"):
        return "ru"
    return "en"


class Translator:
    """Translate dotted keys with English fallback."""

    def __init__(self, language: Language = "system") -> None:
        self.language_mode = language
        self.language = detect_system_language() if language == "system" else language
        self._fallback = self._load("en")
        self._strings = self._load(self.language)

    def set_language(self, language: Language) -> None:
        self.language_mode = language
        self.language = detect_system_language() if language == "system" else language
        self._strings = self._load(self.language)

    def t(self, key: str, **values: object) -> str:
        text = self._lookup(self._strings, key) or self._lookup(self._fallback, key) or key
        if values:
            return text.format(**values)
        return text

    @staticmethod
    def _load(language: str) -> dict[str, object]:
        package = "attentionos.localization.locales"
        with resources.files(package).joinpath(f"{language}.json").open(
            "r", encoding="utf-8"
        ) as handle:
            return json.load(handle)

    @staticmethod
    def _lookup(strings: dict[str, object], key: str) -> str | None:
        value: object = strings
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value if isinstance(value, str) else None
