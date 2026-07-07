"""Time-slot conflict detection helpers for task and habit scheduling."""

from datetime import date, time

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, Task

# ---------------------------------------------------------------------------
# Day-of-week mapping for frequency overlap detection
# ---------------------------------------------------------------------------

FREQ_DAYS: dict[str, set[int]] = {
    "daily": {0, 1, 2, 3, 4, 5, 6},
    "weekdays": {0, 1, 2, 3, 4},
    "weekends": {5, 6},
}
"""Mapping from frequency slug to the set of matching weekday numbers (Mon=0..Sun=6)."""

FREQ_LABELS_RU: dict[str, str] = {
    "daily": "Ежедневно",
    "weekdays": "По будням",
    "weekends": "По выходным",
}
"""Russian labels for frequency values."""

_DAY_NAMES_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


async def is_time_slot_free(
    session: AsyncSession,
    user_id: int,
    task_date: date,
    start_time: time,
    end_time: time | None,
    exclude_task_id: int | None = None,
) -> bool:
    """Check whether a time slot is free for a given user and date.

    Returns ``True`` if **no** existing task overlaps with the proposed
    ``[start_time, end_time)`` interval.  Two cases are handled:

    1. If *end_time* is ``None``, the proposed task is open‑ended.  It
       conflicts with any existing task that is itself open‑ended **or**
       whose end time is after *start_time*.

    2. If *end_time* is provided, the proposed task conflicts with any
       existing task whose start is before the proposed *end_time*
       **and** which is either open‑ended or ends after the proposed
       *start_time*.

    Args:
        session: Active async database session.
        user_id: Internal user identifier.
        task_date: Date of the proposed task.
        start_time: Start time of the proposed task.
        end_time: End time of the proposed task (``None`` = open‑ended).
        exclude_task_id: If provided, exclude this task from the conflict
            check (used when editing an existing task).

    Returns:
        ``True`` if the slot is free, ``False`` if a conflict exists.
    """
    if end_time is None:
        conditions = [
            Task.user_id == user_id,
            Task.date == task_date,
            or_(
                Task.end_time.is_(None),
                Task.end_time > start_time,
            ),
        ]
    else:
        conditions = [
            Task.user_id == user_id,
            Task.date == task_date,
            Task.start_time < end_time,
            or_(
                Task.end_time.is_(None),
                Task.end_time > start_time,
            ),
        ]

    if exclude_task_id is not None:
        conditions.append(Task.id != exclude_task_id)

    conflict_stmt = select(Task).where(and_(*conditions))
    result = await session.execute(conflict_stmt)
    conflicting = result.scalars().first()
    return conflicting is None


# ===========================================================================
# Habit-vs-habit conflict detection
# ===========================================================================


def _time_slots_overlap(
    a_start: time,
    a_end: time | None,
    b_start: time,
    b_end: time | None,
) -> bool:
    """Return ``True`` if two time intervals ``[start, end)`` overlap.

    Handles ``None`` as open-ended (extends to midnight + infinity).
    """
    # a's end is effectively 23:59:59.999... if None
    a_ends_after_b_starts = (a_end is None) or (a_end > b_start)
    b_ends_after_a_starts = (b_end is None) or (b_end > a_start)
    return a_ends_after_b_starts and b_ends_after_a_starts


def _freq_day_overlap(
    freq_a: str,
    freq_b: str,
) -> set[int] | None:
    """Return the set of overlapping weekday numbers, or ``None`` if no overlap.

    Args:
        freq_a, freq_b: Frequency slugs (daily / weekdays / weekends).

    Returns:
        Set of overlapping day numbers (Mon=0..Sun=6) or ``None``.
    """
    days_a = FREQ_DAYS.get(freq_a)
    days_b = FREQ_DAYS.get(freq_b)
    if days_a is None or days_b is None:
        return None
    overlap = days_a & days_b
    return overlap if overlap else None


def _days_display(overlap_days: set[int]) -> str:
    """Return a human-readable string for a set of weekday numbers."""
    if overlap_days == FREQ_DAYS["daily"]:
        return "ежедневно"
    if overlap_days == FREQ_DAYS["weekdays"]:
        return "по будням"
    if overlap_days == FREQ_DAYS["weekends"]:
        return "по выходным"

    ordered = sorted(overlap_days)
    return ", ".join(_DAY_NAMES_RU[d] for d in ordered)


async def check_habit_conflicts(
    session: AsyncSession,
    user_id: int,
    start_time: time,
    end_time: time | None,
    frequency: str,
    exclude_habit_id: int | None = None,
) -> list[Habit]:
    """Find habits that conflict in time **and** overlapping days.

    Returns a list of ``Habit`` ORM objects that overlap with the proposed
    habit.  Empty list means no conflicts.

    Args:
        session: Active async database session.
        user_id: Internal user identifier.
        start_time: Proposed habit start time.
        end_time: Proposed habit end time (``None`` = open-ended).
        frequency: Proposed habit frequency.
        exclude_habit_id: If provided, exclude this habit from the check.

    Returns:
        List of conflicting ``Habit`` objects.
    """
    conditions = [Habit.user_id == user_id]

    if exclude_habit_id is not None:
        conditions.append(Habit.id != exclude_habit_id)

    stmt = select(Habit).where(and_(*conditions))
    result = await session.execute(stmt)
    all_habits = result.scalars().all()

    conflicting: list[Habit] = []
    for habit in all_habits:
        # Frequency (day) overlap
        day_overlap = _freq_day_overlap(frequency, habit.frequency)
        if day_overlap is None:
            continue  # No common days

        # Time slot overlap
        if _time_slots_overlap(
            start_time, end_time,
            habit.start_time, habit.end_time,
        ):
            conflicting.append(habit)

    return conflicting
