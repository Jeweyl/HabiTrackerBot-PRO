"""Shared validation for user account settings (bot + dashboard API)."""

from __future__ import annotations

from datetime import time
from typing import Final

SUPPORTED_LANGUAGES: Final[frozenset[str]] = frozenset({"ru", "en"})

# Same offsets as ``get_timezone_keyboard`` (callback value after set_timezone:).
SUPPORTED_TIMEZONES: Final[frozenset[str]] = frozenset(
    [f"-{n}" for n in range(12, 0, -1)]
    + ["+0"]
    + [f"+{n}" for n in range(1, 15)]
)

SUPPORTED_CHECK_INTERVALS: Final[frozenset[int]] = frozenset(
    {5, 10, 15, 20, 30, 45, 60}
)


def normalize_language(raw: str) -> str:
    """Return ``ru``/``en`` or raise ``ValueError``."""
    code = (raw or "").strip().lower()
    if code not in SUPPORTED_LANGUAGES:
        raise ValueError("language must be 'ru' or 'en'")
    return code


def normalize_timezone(raw: str) -> str:
    """Return bot-compatible offset string (e.g. ``+3``, ``-5``, ``+0``)."""
    value = (raw or "").strip()
    upper = value.upper()
    if upper == "UTC" or upper == "GMT":
        return "+0"
    if upper.startswith("UTC"):
        value = value[3:].strip()
        if not value:
            return "+0"
    if value in {"0"}:
        value = "+0"
    if value and value[0] not in "+-" and value.lstrip("0123456789") == "":
        value = f"+{value}"
    if value not in SUPPORTED_TIMEZONES:
        raise ValueError(
            "timezone must be a UTC offset from -12 to +14 "
            "(e.g. '+3', '-5', '+0')"
        )
    return value


def normalize_check_interval(raw: int) -> int:
    """Return allowed check-in interval minutes or raise ``ValueError``."""
    try:
        minutes = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("check_interval must be an integer") from exc
    if minutes not in SUPPORTED_CHECK_INTERVALS:
        raise ValueError(
            "check_interval must be one of: "
            + ", ".join(str(x) for x in sorted(SUPPORTED_CHECK_INTERVALS))
        )
    return minutes


def parse_reminder_time(raw: str | None) -> time | None:
    """Parse ``HH:MM`` or empty/None as disabled reminder.

    Bot UI uses whole hours (``HH:00``); API accepts any valid ``HH:MM``.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"off", "null", "none"}:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError("reminder_time must be HH:MM or null")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError("reminder_time must be HH:MM or null") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("reminder_time must be a valid clock time")
    return time(hour, minute)


def format_reminder_time(value: time | None) -> str | None:
    """Serialize reminder for JSON API."""
    if value is None:
        return None
    return value.strftime("%H:%M")
