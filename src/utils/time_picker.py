"""Two-step time picker helpers (hour → 15-minute slots)."""

from __future__ import annotations

from datetime import time
from typing import Literal

MINUTES_15: tuple[int, ...] = (0, 15, 30, 45)
"""Allowed minute values for the time picker."""

PENDING_HOUR_KEY = "pending_hour"
"""FSM data key storing the hour chosen in step 1."""

TimeCallbackKind = Literal["hour", "final", "null", "invalid"]


def slot_allowed(slot: time, min_time: time | None) -> bool:
    """Return True if *slot* is strictly after *min_time* (or always if None)."""
    if min_time is None:
        return True
    return slot > min_time


def available_hours(min_time: time | None = None) -> list[int]:
    """Return hours 0–23 that still have at least one allowed 15-min slot."""
    hours: list[int] = []
    for hour in range(24):
        if any(slot_allowed(time(hour, minute), min_time) for minute in MINUTES_15):
            hours.append(hour)
    return hours


def available_minutes(hour: int, min_time: time | None = None) -> list[int]:
    """Return allowed minutes for *hour* given optional *min_time* filter."""
    if hour not in range(24):
        return []
    return [
        minute
        for minute in MINUTES_15
        if slot_allowed(time(hour, minute), min_time)
    ]


def parse_time_callback(
    data: str | None,
) -> tuple[TimeCallbackKind, int | time | None]:
    """Parse a ``time:*`` callback payload.

    Returns:
        ``("hour", hour_int)`` for ``time:hour:HH``
        ``("final", time)`` for ``time:HH:MM`` with MM in {00,15,30,45}
        ``("null", None)`` for ``time:null``
        ``("invalid", None)`` for anything else
    """
    if not data or not data.startswith("time:"):
        return ("invalid", None)

    payload = data[5:]  # strip "time:"
    if payload == "null":
        return ("null", None)

    if payload.startswith("hour:"):
        try:
            hour = int(payload[5:])
        except ValueError:
            return ("invalid", None)
        if hour not in range(24):
            return ("invalid", None)
        return ("hour", hour)

    parts = payload.split(":")
    if len(parts) != 2:
        return ("invalid", None)
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return ("invalid", None)
    if hour not in range(24) or minute not in MINUTES_15:
        return ("invalid", None)
    return ("final", time(hour, minute))
