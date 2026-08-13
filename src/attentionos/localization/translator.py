"""Small JSON translation layer for desktop user-facing strings."""

from __future__ import annotations

import json
import locale
import logging
from importlib import resources
from typing import Literal

Language = Literal["system", "en", "ru"]
logger = logging.getLogger(__name__)


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
        text = self._lookup(self._strings, key)
        if text is None:
            fallback = self._lookup(self._fallback, key)
            if fallback is None:
                logger.warning("Missing translation key: %s", key)
                text = key
            else:
                text = fallback
        if values:
            return text.format(**values)
        return text

    def plural(self, base_key: str, count: int) -> str:
        form = "one" if count == 1 else "other"
        if self.language == "ru":
            mod10 = count % 10
            mod100 = count % 100
            if mod10 == 1 and mod100 != 11:
                form = "one"
            elif 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
                form = "few"
            else:
                form = "many"
        return self.t(f"{base_key}.{form}", count=count)

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
