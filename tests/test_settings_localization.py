from __future__ import annotations

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
