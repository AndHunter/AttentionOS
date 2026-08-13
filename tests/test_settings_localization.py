from __future__ import annotations

import json
import logging
from importlib import resources

from attentionos.localization import Translator
from attentionos.settings import RuntimeSettings, SettingsStore


def test_settings_roundtrip(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = RuntimeSettings()
    settings.preferences.language = "ru"
    settings.tracking.excluded_applications = ["KeePass.exe"]
    store.save(settings)

    loaded = store.load()
    assert loaded.preferences.language == "ru"
    assert loaded.tracking.excluded_applications == ["KeePass.exe"]


def test_localization_fallback() -> None:
    translator = Translator("ru")
    assert translator.t("tracking.start")
    assert translator.t("missing.key") == "missing.key"


def _flatten(data: dict[str, object], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, path))
        elif isinstance(value, str):
            result[path] = value
    return result


def _load_locale(language: str) -> dict[str, str]:
    package = "attentionos.localization.locales"
    with resources.files(package).joinpath(f"{language}.json").open(
        "r",
        encoding="utf-8",
    ) as handle:
        return _flatten(json.load(handle))


def test_translation_resources_have_identical_non_empty_keys() -> None:
    en = _load_locale("en")
    ru = _load_locale("ru")
    assert set(en) == set(ru)
    assert all(value.strip() for value in en.values())
    assert all(value.strip() for value in ru.values())


def test_unknown_translation_key_is_logged(caplog) -> None:
    translator = Translator("en")
    with caplog.at_level(logging.WARNING):
        assert translator.t("missing.key") == "missing.key"
    assert "Missing translation key: missing.key" in caplog.text


def test_pluralization_ru_and_en() -> None:
    assert Translator("en").plural("units.blocks", 2) == "2 blocks"
    ru = Translator("ru")
    assert ru.plural("units.blocks", 1) == "1 блок"
    assert ru.plural("units.blocks", 2) == "2 блока"
    assert ru.plural("units.blocks", 5) == "5 блоков"
