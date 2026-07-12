"""Task generation from habits — lazy, conflict‑aware scheduling."""

from __future__ import annotations

import logging
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, Task
from src.db.session import get_db
from src.utils.conflict import is_time_slot_free

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frequency helpers
# ---------------------------------------------------------------------------

_FREQ_MATCHERS = {
    "daily": lambda d: True,
    "weekdays": lambda d: d.weekday() < 5,  # 0=Mon … 4=Fri
    "weekends": lambda d: d.weekday() >= 5,  # 5=Sat, 6=Sun
}


def _matches_frequency(day: date, frequency: str) -> bool:
    """Return ``True`` if *day* satisfies the habit frequency.

    Args:
        day: The date to check.
        frequency: One of ``"daily"``, ``"weekdays"``, ``"weekends"``.

    Returns:
        ``True`` if *day* matches the frequency.
    """
    matcher = _FREQ_MATCHERS.get(frequency)
    return matcher(day) if matcher else False


# ===========================================================================
# Core generation for a single habit
# ===========================================================================


async def generate_tasks_for_habit(
    habit_id: int,
    days_ahead: int = 30,
    today_override: date | None = None,
    *,
    session: AsyncSession | None = None,
    now_time: time | None = None,
) -> int:
    """Create ``Task`` rows for every day in the next *days_ahead* that
    matches the habit's frequency, unless a task already exists or the
    time slot is occupied.

    When *session* is provided, the caller owns the transaction (no
    commit/close here).  Otherwise a new session is opened and committed.

    Past policy: never create tasks for dates before *today*.  For
    *today* itself, if *now_time* is provided and the habit's
    ``start_time`` is already in the past (``start_time <= now_time``),
    skip today's task.

    Args:
        habit_id: ID of the habit to generate tasks for.
        days_ahead: Number of days (starting from today) to cover.
        today_override: If provided, use this date as "today" instead of
            ``date.today()``.  Useful for deterministic testing.
        session: Optional existing async session (atomic apply path).
        now_time: Optional local clock time used to skip past slots today.

    Returns:
        Number of tasks created.
    """
    if session is not None:
        return await _generate_tasks_for_habit_impl(
            session,
            habit_id,
            days_ahead=days_ahead,
            today_override=today_override,
            now_time=now_time,
            do_commit=False,
        )

    async with get_db() as own_session:
        return await _generate_tasks_for_habit_impl(
            own_session,
            habit_id,
            days_ahead=days_ahead,
            today_override=today_override,
            now_time=now_time,
            do_commit=True,
        )


async def _generate_tasks_for_habit_impl(
    session: AsyncSession,
    habit_id: int,
    *,
    days_ahead: int,
    today_override: date | None,
    now_time: time | None,
    do_commit: bool,
) -> int:
    """Internal implementation of task generation for one habit."""
    habit = await session.get(Habit, habit_id)
    if habit is None:
        logger.warning("generate_tasks_for_habit: habit %d not found", habit_id)
        return 0

    today = today_override if today_override is not None else date.today()
    created = 0
    for offset in range(max(0, int(days_ahead or 0))):
        target_date = today + timedelta(days=offset)

        # 0. Past-today policy: skip today if start already passed
        if (
            offset == 0
            and now_time is not None
            and habit.start_time is not None
        ):
            start = habit.start_time.replace(second=0, microsecond=0)
            current = now_time.replace(second=0, microsecond=0)
            if start <= current:
                logger.debug(
                    "Skipping today for habit %d: start %s <= now %s",
                    habit_id,
                    start.strftime("%H:%M"),
                    current.strftime("%H:%M"),
                )
                continue

        # 1. Frequency check
        if not _matches_frequency(target_date, habit.frequency):
            continue

        # 2. Skip if a task for this habit+date already exists
        exists_stmt = select(Task).where(
            Task.habit_id == habit_id,
            Task.date == target_date,
        )
        exists_result = await session.execute(exists_stmt)
        if exists_result.scalar_one_or_none() is not None:
            continue

        # 3. Conflict check
        if not await is_time_slot_free(
            session,
            habit.user_id,
            target_date,
            habit.start_time,
            habit.end_time,
        ):
            logger.debug(
                "Slot occupied for habit %d on %s — skipping",
                habit_id,
                target_date.isoformat(),
            )
            continue

        # 4. Create the task
        task = Task(
            user_id=habit.user_id,
            habit_id=habit.id,
            title=habit.title,
            date=target_date,
            start_time=habit.start_time,
            end_time=habit.end_time,
            is_completed=False,
            is_placeholder=False,
        )
        session.add(task)
        created += 1

    if do_commit:
        await session.commit()

    if created:
        logger.info(
            "Generated %d tasks for habit %d (%s)",
            created,
            habit_id,
            habit.title,
        )
    return created



# ===========================================================================
# Lazy generation for a user + date range
# ===========================================================================


async def lazy_generate_for_range(
    user_id: int,
    start_date: date,
    days: int = 7,
    today_override: date | None = None,
) -> None:
    """Ensure tasks exist for all of a user's habits in the given range.

    Iterates over every habit belonging to *user_id* and, for each day
    from *start_date* to ``start_date + days - 1``, creates a task if
    the frequency matches and no task exists yet.  Slots already occupied
    by manual tasks are respected.

    Args:
        user_id: Internal user identifier.
        start_date: First date to check.
        days: Number of consecutive days to cover (default 7).
    """
    async with get_db() as session:
        habits_stmt = select(Habit).where(Habit.user_id == user_id)
        result = await session.execute(habits_stmt)
        habits = result.scalars().all()

        if not habits:
            return

        total_created = 0
        for habit in habits:
            for offset in range(days):
                target_date = start_date + timedelta(days=offset)

                # Frequency
                if not _matches_frequency(target_date, habit.frequency):
                    continue

                # Already exists?
                exists_stmt = select(Task).where(
                    Task.habit_id == habit.id,
                    Task.date == target_date,
                )
                exists_result = await session.execute(exists_stmt)
                if exists_result.scalar_one_or_none() is not None:
                    continue

                # Conflict?
                if not await is_time_slot_free(
                    session,
                    habit.user_id,
                    target_date,
                    habit.start_time,
                    habit.end_time,
                ):
                    continue

                task = Task(
                    user_id=habit.user_id,
                    habit_id=habit.id,
                    title=habit.title,
                    date=target_date,
                    start_time=habit.start_time,
                    end_time=habit.end_time,
                    is_completed=False,
                    is_placeholder=False,
                )
                session.add(task)
                total_created += 1

        await session.commit()

        if total_created:
            logger.info(
                "Lazy-generated %d tasks for user %d from %s (+%d days)",
                total_created,
                user_id,
                start_date.isoformat(),
                days,
            )
