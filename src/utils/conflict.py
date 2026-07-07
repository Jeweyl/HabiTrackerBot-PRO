"""Time-slot conflict detection helpers for task scheduling."""

from datetime import date, time

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Task


async def is_time_slot_free(
    session: AsyncSession,
    user_id: int,
    task_date: date,
    start_time: time,
    end_time: time | None,
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

    Returns:
        ``True`` if the slot is free, ``False`` if a conflict exists.
    """
    if end_time is None:
        # New task has no end — conflicts with any task that is
        # open-ended OR ends after new_start_time
        conflict_condition = and_(
            Task.user_id == user_id,
            Task.date == task_date,
            or_(
                Task.end_time.is_(None),
                Task.end_time > start_time,
            ),
        )
    else:
        # New task has an end — conflicts with any task that starts
        # before new_end AND is open-ended OR ends after new_start
        conflict_condition = and_(
            Task.user_id == user_id,
            Task.date == task_date,
            Task.start_time < end_time,
            or_(
                Task.end_time.is_(None),
                Task.end_time > start_time,
            ),
        )

    conflict_stmt = select(Task).where(conflict_condition)
    result = await session.execute(conflict_stmt)
    conflicting = result.scalars().first()
    return conflicting is None