"""Read-only statistics queries for the dashboard API (and bot reuse)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, Task


MAX_STATS_RANGE_DAYS = 90


@dataclass(frozen=True, slots=True)
class OverviewStats:
    """Aggregate stats for a closed date window."""

    days: int
    from_date: date
    to_date: date
    total_tasks: int
    completed_tasks: int
    missed_tasks: int
    completion_rate: float
    streak: int
    habits_count: int


@dataclass(frozen=True, slots=True)
class DailyPoint:
    """Per-day task completion counts."""

    date: date
    total: int
    completed: int
    missed: int


@dataclass(frozen=True, slots=True)
class ScheduleItem:
    """Single task row for schedule/calendar views."""

    id: int
    title: str
    date: date
    start_time: str
    end_time: str | None
    is_completed: bool
    is_placeholder: bool
    habit_id: int | None


@dataclass(frozen=True, slots=True)
class HabitBreakdownItem:
    """Per-habit completion stats for a rolling window."""

    habit_id: int
    title: str
    total: int
    completed: int
    missed: int
    completion_rate: float


def validate_days(days: int) -> int:
    """Validate overview ``days`` window (1..MAX_STATS_RANGE_DAYS)."""
    if days is None or days < 1 or days > MAX_STATS_RANGE_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_STATS_RANGE_DAYS}")
    return days


def validate_date_range(from_date: date, to_date: date) -> tuple[date, date]:
    """Validate inclusive date range and max span."""
    if from_date > to_date:
        raise ValueError("from must be on or before to")
    span = (to_date - from_date).days + 1
    if span > MAX_STATS_RANGE_DAYS:
        raise ValueError(f"date range must not exceed {MAX_STATS_RANGE_DAYS} days")
    return from_date, to_date


async def calculate_streak(
    session: AsyncSession,
    user_id: int,
    today: date,
    *,
    days: int = 7,
) -> int:
    """Count consecutive fully-completed days going backwards from *today*.

    A day with no tasks neither extends nor breaks the streak.
    A day with tasks that are not all completed breaks the streak.
    """
    streak = 0
    for offset in range(days):
        check_date = today - timedelta(days=offset)
        total_stmt = select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.date == check_date,
        )
        total_result = await session.execute(total_stmt)
        total = total_result.scalar() or 0

        if total == 0:
            continue

        completed_stmt = select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.date == check_date,
            Task.is_completed.is_(True),
        )
        completed_result = await session.execute(completed_stmt)
        completed = completed_result.scalar() or 0

        if completed == total:
            streak += 1
        else:
            break

    return streak


async def get_overview(
    session: AsyncSession,
    user_id: int,
    *,
    days: int = 7,
    today: date | None = None,
) -> OverviewStats:
    """Return aggregate stats for the last *days* including *today*."""
    days = validate_days(days)
    today = today or date.today()
    since = today - timedelta(days=days - 1)

    total_stmt = select(func.count(Task.id)).where(
        Task.user_id == user_id,
        Task.date >= since,
        Task.date <= today,
    )
    total_result = await session.execute(total_stmt)
    total_count = int(total_result.scalar() or 0)

    completed_stmt = select(func.count(Task.id)).where(
        Task.user_id == user_id,
        Task.date >= since,
        Task.date <= today,
        Task.is_completed.is_(True),
    )
    completed_result = await session.execute(completed_stmt)
    completed_count = int(completed_result.scalar() or 0)

    missed_count = total_count - completed_count
    if total_count == 0:
        completion_rate = 0.0
    else:
        completion_rate = round(completed_count / total_count * 100, 1)

    habits_stmt = select(func.count(Habit.id)).where(Habit.user_id == user_id)
    habits_result = await session.execute(habits_stmt)
    habits_count = int(habits_result.scalar() or 0)

    streak = await calculate_streak(session, user_id, today, days=days)

    return OverviewStats(
        days=days,
        from_date=since,
        to_date=today,
        total_tasks=total_count,
        completed_tasks=completed_count,
        missed_tasks=missed_count,
        completion_rate=completion_rate,
        streak=streak,
        habits_count=habits_count,
    )


async def get_daily_series(
    session: AsyncSession,
    user_id: int,
    from_date: date,
    to_date: date,
) -> list[DailyPoint]:
    """Return per-day counts with gap-fill zeros for missing days."""
    from_date, to_date = validate_date_range(from_date, to_date)

    # Aggregate in Python for SQLite + Postgres bool portability.
    rows_stmt = select(Task.date, Task.is_completed).where(
        Task.user_id == user_id,
        Task.date >= from_date,
        Task.date <= to_date,
    )
    result = await session.execute(rows_stmt)
    rows = result.all()

    by_day: dict[date, list[int]] = {}
    for task_date, is_completed in rows:
        bucket = by_day.setdefault(task_date, [0, 0])
        bucket[0] += 1
        if is_completed:
            bucket[1] += 1

    series: list[DailyPoint] = []
    cursor = from_date
    while cursor <= to_date:
        total, completed = by_day.get(cursor, [0, 0])
        series.append(
            DailyPoint(
                date=cursor,
                total=total,
                completed=completed,
                missed=total - completed,
            )
        )
        cursor += timedelta(days=1)
    return series


async def get_schedule(
    session: AsyncSession,
    user_id: int,
    from_date: date,
    to_date: date,
) -> list[ScheduleItem]:
    """Return tasks in the inclusive date range ordered by date/time."""
    from_date, to_date = validate_date_range(from_date, to_date)

    stmt = (
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.date >= from_date,
            Task.date <= to_date,
        )
        .order_by(Task.date.asc(), Task.start_time.asc(), Task.id.asc())
    )
    result = await session.execute(stmt)
    tasks: Sequence[Task] = result.scalars().all()

    items: list[ScheduleItem] = []
    for task in tasks:
        end = task.end_time.strftime("%H:%M") if task.end_time else None
        items.append(
            ScheduleItem(
                id=task.id,
                title=task.title,
                date=task.date,
                start_time=task.start_time.strftime("%H:%M"),
                end_time=end,
                is_completed=bool(task.is_completed),
                is_placeholder=bool(task.is_placeholder),
                habit_id=task.habit_id,
            )
        )
    return items


async def get_habit_breakdown(
    session: AsyncSession,
    user_id: int,
    *,
    days: int = 7,
    today: date | None = None,
) -> list[HabitBreakdownItem]:
    """Return per-habit completion stats for the last *days* including *today*.

    Habits with zero tasks in the window still appear with zero counts so the
    UI can show an empty-but-known habit list. Never raises for empty data.
    """
    days = validate_days(days)
    today = today or date.today()
    since = today - timedelta(days=days - 1)

    habits_stmt = select(Habit).where(Habit.user_id == user_id).order_by(Habit.id.asc())
    habits_result = await session.execute(habits_stmt)
    habits: Sequence[Habit] = habits_result.scalars().all()

    if not habits:
        return []

    task_stmt = select(Task.habit_id, Task.is_completed).where(
        Task.user_id == user_id,
        Task.date >= since,
        Task.date <= today,
        Task.habit_id.is_not(None),
    )
    task_result = await session.execute(task_stmt)
    rows = task_result.all()

    counts: dict[int, list[int]] = {}
    for habit_id, is_completed in rows:
        if habit_id is None:
            continue
        bucket = counts.setdefault(int(habit_id), [0, 0])
        bucket[0] += 1
        if is_completed:
            bucket[1] += 1

    items: list[HabitBreakdownItem] = []
    for habit in habits:
        total, completed = counts.get(habit.id, [0, 0])
        missed = total - completed
        if total == 0:
            rate = 0.0
        else:
            rate = round(completed / total * 100, 1)
        items.append(
            HabitBreakdownItem(
                habit_id=habit.id,
                title=habit.title or f"Habit #{habit.id}",
                total=total,
                completed=completed,
                missed=missed,
                completion_rate=rate,
            )
        )
    return items
