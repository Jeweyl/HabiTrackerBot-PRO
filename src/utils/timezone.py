"""Timezone helpers shared by reminder and check-in services."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def parse_timezone_offset(tz_value: str) -> timedelta:
    """Parse timezone values like ``UTC``, ``+3``, ``-5`` into a timedelta.

    Args:
        tz_value: Stored user timezone string.

    Returns:
        Timedelta offset from UTC. Unknown values fall back to UTC.
    """
    if not tz_value or tz_value.upper() == "UTC":
        return timedelta(0)

    value = tz_value.strip()
    if value.upper().startswith("UTC"):
        value = value[3:]

    if not value or value in {"0", "+0", "-0"}:
        return timedelta(0)

    try:
        hours = int(value)
    except ValueError:
        logger.warning("Unknown timezone value '%s', falling back to UTC", tz_value)
        return timedelta(0)

    return timedelta(hours=hours)


def local_now(tz_value: str) -> datetime:
    """Return current local datetime for the given timezone offset.

    Args:
        tz_value: Stored user timezone string.

    Returns:
        Timezone-aware datetime in the user's local offset.
    """
    offset = parse_timezone_offset(tz_value)
    return datetime.now(timezone.utc).astimezone(timezone(offset))
