"""Find free time slots for rescheduling tasks within a day."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Sequence

from src.utils.time_picker import MINUTES_15


def _to_minutes(t: time) -> int:
    """Convert a time to minutes from midnight."""
    return t.hour * 60 + t.minute


def _intervals_overlap(
    a_start: int,
    a_end: int | None,
    b_start: int,
    b_end: int | None,
) -> bool:
    """Return True if two half-open intervals [start, end) overlap.

    ``None`` end means open-ended (extends past end of day).
    """
    a_ends_after_b_starts = a_end is None or a_end > b_start
    b_ends_after_a_starts = b_end is None or b_end > a_start
    return a_ends_after_b_starts and b_ends_after_a_starts


def task_duration_minutes(start: time, end: time | None) -> int | None:
    """Return duration in minutes, or ``None`` for open-ended tasks."""
    if end is None:
        return None
    duration = _to_minutes(end) - _to_minutes(start)
    return duration if duration > 0 else None


def find_free_slots(
    *,
    occupied: Sequence[tuple[time, time | None]],
    duration_minutes: int | None,
    after: time,
    day: date | None = None,  # reserved for future multi-day use
) -> list[time]:
    """Return free start times on a 15-minute grid after *after*.

    Args:
        occupied: Existing tasks as ``(start_time, end_time)`` pairs.
            ``end_time=None`` means open-ended.
        duration_minutes: Required contiguous free duration. ``None`` means
            the candidate is open-ended (conflicts with any overlapping
            open-ended or later-ending task).
        after: Only slots strictly after this local time are returned.
        day: Unused; kept for API symmetry with date-scoped callers.

    Returns:
        Sorted list of free start times (15-min grid).
    """
    del day  # unused for now

    occupied_mins: list[tuple[int, int | None]] = [
        (_to_minutes(s), _to_minutes(e) if e is not None else None)
        for s, e in occupied
    ]

    after_mins = _to_minutes(after)
    candidates: list[time] = []

    for hour in range(24):
        for minute in MINUTES_15:
            start_mins = hour * 60 + minute
            if start_mins <= after_mins:
                continue

            if duration_minutes is None:
                end_mins: int | None = None
            else:
                end_mins = start_mins + duration_minutes
                # Must fit entirely within the same calendar day.
                if end_mins > 24 * 60:
                    continue

            conflict = False
            for occ_start, occ_end in occupied_mins:
                if _intervals_overlap(start_mins, end_mins, occ_start, occ_end):
                    conflict = True
                    break
            if not conflict:
                candidates.append(time(hour, minute))

    return candidates


def end_of_local_day_utc(local_dt: datetime) -> datetime:
    """Return UTC datetime for 23:59:59.999999 of *local_dt*'s calendar day."""
    if local_dt.tzinfo is None:
        raise ValueError("local_dt must be timezone-aware")
    local_eod = datetime.combine(
        local_dt.date(),
        time(23, 59, 59, 999999),
        tzinfo=local_dt.tzinfo,
    )
    return local_eod.astimezone(timezone.utc)


def shift_end_time(
    old_start: time,
    old_end: time | None,
    new_start: time,
) -> time | None:
    """Preserve duration when moving a task; keep ``None`` for open-ended."""
    duration = task_duration_minutes(old_start, old_end)
    if duration is None:
        return None
    new_end_mins = _to_minutes(new_start) + duration
    if new_end_mins > 24 * 60:
        # Clamp to end of day if it would overflow (should be rare after slot filter).
        new_end_mins = 24 * 60
    # Represent midnight-next as 23:59 for storage if needed; prefer exact minutes.
    if new_end_mins == 24 * 60:
        return time(23, 59)
    return time(new_end_mins // 60, new_end_mins % 60)
