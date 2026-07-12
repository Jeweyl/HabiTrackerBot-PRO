"""Localized BotFather/API profile copy for HabiTracker.

Telegram limits:
    - description: 512 characters
    - short description (about): 120 characters

``None`` language key = default fallback (used when client language
has no dedicated localization). Default is English.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Short description / About (≤ 120)
# ---------------------------------------------------------------------------

ABOUT: Final[dict[str | None, str]] = {
    None: (
        "Habits without chaos: AI goals, conflict-free schedule, "
        "check-ins & stats."
    ),
    "en": (
        "Habits without chaos: AI goals, conflict-free schedule, "
        "check-ins & stats."
    ),
    "ru": (
        "Привычки без хаоса: AI-цели, расписание без конфликтов, "
        "check-in и статистика."
    ),
}

# ---------------------------------------------------------------------------
# Description — empty-chat welcome screen (≤ 512)
# CTA: type /start (no Start button in some clients / deep links)
# ---------------------------------------------------------------------------

DESCRIPTIONS: Final[dict[str | None, str]] = {
    None: (
        "🌱 HabiTracker — habits that actually fit your day\n"
        "\n"
        "Not a dumb checklist:\n"
        "• 🤖 AI turns vague goals into a SMART habit + time slot\n"
        "• ⏰ Conflict-free schedule\n"
        "• ✅ Smart check-ins, no spam\n"
        "• 📊 Streaks, 7/30-day stats + web dashboard\n"
        "\n"
        "Type /start to begin — build your first habit in minutes."
    ),
    "en": (
        "🌱 HabiTracker — habits that actually fit your day\n"
        "\n"
        "Not a dumb checklist:\n"
        "• 🤖 AI turns vague goals into a SMART habit + time slot\n"
        "• ⏰ Conflict-free schedule\n"
        "• ✅ Smart check-ins, no spam\n"
        "• 📊 Streaks, 7/30-day stats + web dashboard\n"
        "\n"
        "Type /start to begin — build your first habit in minutes."
    ),
    "ru": (
        "🌱 HabiTracker — привычки, которые реально встраиваются в день\n"
        "\n"
        "Не чеклист «сделал/не сделал», а система:\n"
        "• 🤖 AI превращает «хочу больше двигаться» в SMART-цель и слот\n"
        "• ⏰ Расписание без наложений — конфликты ловятся до сохранения\n"
        "• ✅ Check-in: «Выполнили…?» в нужный момент, без спама\n"
        "• 📊 Streak, % за 7/30 дней + web-дашборд с графиками\n"
        "\n"
        "Напишите /start, чтобы начать — первая привычка за пару минут."
    ),
}

# ---------------------------------------------------------------------------
# Bot commands menu (only handlers that exist as slash commands)
# ---------------------------------------------------------------------------

COMMANDS: Final[dict[str | None, list[tuple[str, str]]]] = {
    None: [
        ("start", "Start the bot / open main menu"),
    ],
    "en": [
        ("start", "Start the bot / open main menu"),
    ],
    "ru": [
        ("start", "Запустить бота / открыть главное меню"),
    ],
}

_DESC_MAX = 512
_ABOUT_MAX = 120


def validate_profile_texts() -> None:
    """Raise ``ValueError`` if any copy exceeds Telegram limits."""
    for lang, text in DESCRIPTIONS.items():
        if len(text) > _DESC_MAX:
            raise ValueError(
                f"description[{lang!r}] is {len(text)} chars "
                f"(max {_DESC_MAX})"
            )
    for lang, text in ABOUT.items():
        if len(text) > _ABOUT_MAX:
            raise ValueError(
                f"about[{lang!r}] is {len(text)} chars (max {_ABOUT_MAX})"
            )
