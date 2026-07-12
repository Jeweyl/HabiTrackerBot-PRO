"""Unit tests for bot profile copy limits and structure."""

from src.bot_profile.texts import ABOUT, COMMANDS, DESCRIPTIONS, validate_profile_texts


def test_validate_profile_texts_ok() -> None:
    validate_profile_texts()


def test_description_mentions_start_command() -> None:
    assert "/start" in DESCRIPTIONS["ru"]
    assert "/start" in DESCRIPTIONS["en"]
    assert "/start" in DESCRIPTIONS[None]


def test_description_within_limit() -> None:
    for lang, text in DESCRIPTIONS.items():
        assert len(text) <= 512, lang


def test_about_within_limit() -> None:
    for lang, text in ABOUT.items():
        assert len(text) <= 120, lang


def test_commands_include_start() -> None:
    for lang, cmds in COMMANDS.items():
        names = [c for c, _ in cmds]
        assert "start" in names, lang
