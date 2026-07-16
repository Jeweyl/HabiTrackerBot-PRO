"""Unit tests for the i18n helper."""

from __future__ import annotations

from src.i18n import normalize_lang, t


class TestNormalizeLang:
    def test_ru_and_en(self) -> None:
        assert normalize_lang("ru") == "ru"
        assert normalize_lang("en") == "en"
        assert normalize_lang("EN") == "en"
        assert normalize_lang("Ru") == "ru"

    def test_unknown_falls_back_to_ru(self) -> None:
        assert normalize_lang("fr") == "ru"
        assert normalize_lang("es") == "ru"
        assert normalize_lang("jp") == "ru"
        assert normalize_lang("") == "ru"
        assert normalize_lang(None) == "ru"

    def test_locale_prefix(self) -> None:
        assert normalize_lang("en-US") == "en"
        assert normalize_lang("ru_RU") == "ru"


class TestTranslate:
    def test_settings_title_ru(self) -> None:
        assert "Настройки" in t("settings.title", "ru")

    def test_settings_title_en(self) -> None:
        text = t("settings.title", "en")
        assert "Settings" in text
        assert "Настройки" not in text

    def test_missing_key_no_crash(self) -> None:
        assert t("this.key.does.not.exist", "en") == "this.key.does.not.exist"
        assert t("this.key.does.not.exist", "ru") == "this.key.does.not.exist"

    def test_unknown_lang_uses_ru(self) -> None:
        assert t("settings.title", "fr") == t("settings.title", "ru")

    def test_format_kwargs(self) -> None:
        text = t("checkin.prompt", "en", title="Run")
        assert "Run" in text
        assert "Did you complete" in text

    def test_missing_format_kwarg_no_crash(self) -> None:
        # Template expects {title}; omit it — must not raise.
        text = t("checkin.prompt", "ru")
        assert "{title}" in text or "Выполнили" in text

    def test_main_menu_labels_differ(self) -> None:
        assert t("main.settings", "ru") != t("main.settings", "en")
        assert "Settings" in t("main.settings", "en")
