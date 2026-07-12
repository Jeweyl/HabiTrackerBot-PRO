"""Unit tests for AI ProposePlan apply (B3)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, Task, User
from src.services.ai_apply import (
    apply_propose_plan,
    resolve_plan_schedule,
)
from src.services.ai_schema import ProposePlan


# ---------------------------------------------------------------------------
# resolve_plan_schedule
# ---------------------------------------------------------------------------


def test_resolve_duration_15_derives_end() -> None:
    """15-min plan without end_time → end = start + 15m."""
    plan = {
        "type": "propose_plan",
        "title": "Stretch",
        "start_time": "07:00",
        "end_time": None,
        "frequency": "daily",
        "duration_minutes": 15,
        "comment": "",
    }
    resolved = resolve_plan_schedule(plan)
    assert resolved is not None
    assert resolved.start_time == time(7, 0)
    assert resolved.end_time == time(7, 15)
    assert resolved.duration_minutes == 15
    assert resolved.frequency == "daily"
    assert resolved.title == "Stretch"


def test_resolve_start_end_duration_consistent() -> None:
    """start+end+duration matching is accepted."""
    plan = ProposePlan(
        type="propose_plan",
        title="Run",
        start_time="08:00",
        end_time="08:30",
        frequency="weekdays",
        duration_minutes=30,
        comment="ok",
    )
    resolved = resolve_plan_schedule(plan)
    assert resolved is not None
    assert resolved.end_time == time(8, 30)
    assert resolved.duration_minutes == 30
    assert resolved.frequency == "weekdays"


def test_resolve_duration_mismatch_rejected() -> None:
    """Disagreeing duration vs end-start → None (no auto-fix)."""
    plan = {
        "title": "Bad",
        "start_time": "08:00",
        "end_time": "08:30",
        "duration_minutes": 15,
        "frequency": "daily",
    }
    assert resolve_plan_schedule(plan) is None


def test_resolve_missing_end_and_duration_no_hardcoded() -> None:
    """Missing end and duration must NOT fall back to 08:00–09:00."""
    plan = {
        "title": "No times",
        "start_time": "10:00",
        "end_time": None,
        "duration_minutes": None,
        "frequency": "daily",
    }
    assert resolve_plan_schedule(plan) is None


def test_resolve_none_and_empty() -> None:
    """None / empty plan → None, no crash."""
    assert resolve_plan_schedule(None) is None
    assert resolve_plan_schedule({}) is None
    assert resolve_plan_schedule({"title": ""}) is None


def test_resolve_fallback_title() -> None:
    """Empty plan title uses fallback_title."""
    plan = {
        "start_time": "06:00",
        "duration_minutes": 30,
        "frequency": "weekends",
    }
    resolved = resolve_plan_schedule(plan, fallback_title="From FSM")
    assert resolved is not None
    assert resolved.title == "From FSM"
    assert resolved.end_time == time(6, 30)
    assert resolved.frequency == "weekends"


def test_resolve_invalid_frequency_defaults_daily() -> None:
    plan = {
        "title": "X",
        "start_time": "09:00",
        "end_time": "09:15",
        "frequency": "monthly",
    }
    resolved = resolve_plan_schedule(plan)
    assert resolved is not None
    assert resolved.frequency == "daily"


def test_resolve_schedule_ops_fill_start() -> None:
    """schedule_ops can fill missing start_time."""
    plan = {
        "title": "Ops",
        "start_time": None,
        "end_time": None,
        "duration_minutes": 15,
        "schedule_ops": [
            {
                "op": "set_schedule",
                "start_time": "12:00",
                "end_time": None,
                "frequency": "daily",
            }
        ],
    }
    resolved = resolve_plan_schedule(plan)
    assert resolved is not None
    assert resolved.start_time == time(12, 0)
    assert resolved.end_time == time(12, 15)


# ---------------------------------------------------------------------------
# apply_propose_plan
# ---------------------------------------------------------------------------


async def _make_user(session: AsyncSession, telegram_id: int = 42) -> User:
    user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_apply_creates_habit_and_tasks(async_session: AsyncSession) -> None:
    """Happy path: habit times from plan + tasks for frequency."""
    user = await _make_user(async_session)
    plan = {
        "type": "propose_plan",
        "title": "Morning run",
        "start_time": "07:00",
        "end_time": "07:15",
        "frequency": "daily",
        "duration_minutes": 15,
        "comment": "go",
    }
    # Fixed "now" early morning so today is included
    now_local = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)
    result = await apply_propose_plan(
        async_session,
        user,
        plan,
        days_ahead=7,
        now_local=now_local,
        today_override=date(2026, 7, 1),
    )
    await async_session.commit()

    assert result.status == "ok"
    assert result.habit is not None
    assert result.habit.start_time == time(7, 0)
    assert result.habit.end_time == time(7, 15)
    assert result.habit.frequency == "daily"
    assert result.tasks_created == 7

    tasks = (
        await async_session.execute(
            select(Task).where(Task.habit_id == result.habit.id)
        )
    ).scalars().all()
    assert len(tasks) == 7
    assert all(t.start_time == time(7, 0) for t in tasks)
    assert all(t.end_time == time(7, 15) for t in tasks)


@pytest.mark.asyncio
async def test_apply_weekdays_frequency(async_session: AsyncSession) -> None:
    """Tasks only on weekdays for frequency=weekdays."""
    user = await _make_user(async_session, telegram_id=43)
    plan = {
        "title": "Office stretch",
        "start_time": "09:00",
        "end_time": "09:15",
        "frequency": "weekdays",
        "duration_minutes": 15,
    }
    # Wed 2026-07-01 → 7 days: Wed–Tue = 5 weekdays
    now_local = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    result = await apply_propose_plan(
        async_session,
        user,
        plan,
        days_ahead=7,
        now_local=now_local,
        today_override=date(2026, 7, 1),
    )
    await async_session.commit()

    assert result.status == "ok"
    assert result.tasks_created == 5


@pytest.mark.asyncio
async def test_apply_conflict_no_write(async_session: AsyncSession) -> None:
    """Overlapping existing habit → conflict, no new habit."""
    user = await _make_user(async_session, telegram_id=44)
    existing = Habit(
        user_id=user.id,
        title="Existing",
        start_time=time(8, 0),
        end_time=time(9, 0),
        frequency="daily",
    )
    async_session.add(existing)
    await async_session.commit()

    plan = {
        "title": "Overlap",
        "start_time": "08:30",
        "end_time": "08:45",
        "frequency": "daily",
        "duration_minutes": 15,
    }
    result = await apply_propose_plan(async_session, user, plan)
    await async_session.commit()

    assert result.status == "conflict"
    assert len(result.conflicting) >= 1
    count = await async_session.scalar(select(func.count()).select_from(Habit))
    assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_apply_force_overrides_conflict(async_session: AsyncSession) -> None:
    """force=True creates habit despite conflict."""
    user = await _make_user(async_session, telegram_id=45)
    async_session.add(
        Habit(
            user_id=user.id,
            title="Existing",
            start_time=time(8, 0),
            end_time=time(9, 0),
            frequency="daily",
        )
    )
    await async_session.commit()

    plan = {
        "title": "Forced",
        "start_time": "08:30",
        "end_time": "08:45",
        "frequency": "daily",
        "duration_minutes": 15,
    }
    now_local = datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)
    result = await apply_propose_plan(
        async_session,
        user,
        plan,
        force=True,
        days_ahead=3,
        now_local=now_local,
        today_override=date(2026, 7, 1),
    )
    await async_session.commit()

    assert result.status == "ok"
    assert result.habit is not None
    assert result.habit.title == "Forced"
    count = await async_session.scalar(select(func.count()).select_from(Habit))
    assert int(count or 0) == 2


@pytest.mark.asyncio
async def test_apply_skips_today_when_start_past(
    async_session: AsyncSession,
) -> None:
    """If local now is after start_time, no task for today."""
    user = await _make_user(async_session, telegram_id=46)
    plan = {
        "title": "Late",
        "start_time": "08:00",
        "end_time": "08:15",
        "frequency": "daily",
        "duration_minutes": 15,
    }
    # now 10:00 > start 08:00 → skip today; 2 more days → 2 tasks
    now_local = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    result = await apply_propose_plan(
        async_session,
        user,
        plan,
        days_ahead=3,
        now_local=now_local,
        today_override=date(2026, 7, 1),
    )
    await async_session.commit()

    assert result.status == "ok"
    assert result.tasks_created == 2
    tasks = (
        await async_session.execute(
            select(Task).where(Task.habit_id == result.habit.id)
        )
    ).scalars().all()
    dates = {t.date for t in tasks}
    assert date(2026, 7, 1) not in dates
    assert date(2026, 7, 2) in dates
    assert date(2026, 7, 3) in dates


@pytest.mark.asyncio
async def test_apply_invalid_plan_error(async_session: AsyncSession) -> None:
    """Invalid plan → error status, no habit."""
    user = await _make_user(async_session, telegram_id=47)
    result = await apply_propose_plan(async_session, user, None)
    assert result.status == "error"
    count = await async_session.scalar(select(func.count()).select_from(Habit))
    assert int(count or 0) == 0


@pytest.mark.asyncio
async def test_apply_duration_only_end_equals_start_plus_duration(
    async_session: AsyncSession,
) -> None:
    """Criterion: 15 min plan → end = start + 15m persisted on Habit."""
    user = await _make_user(async_session, telegram_id=48)
    plan = {
        "title": "Breath",
        "start_time": "21:00",
        "end_time": None,
        "duration_minutes": 15,
        "frequency": "daily",
    }
    now_local = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)
    result = await apply_propose_plan(
        async_session,
        user,
        plan,
        days_ahead=1,
        now_local=now_local,
        today_override=date(2026, 7, 1),
    )
    await async_session.commit()

    assert result.status == "ok"
    assert result.habit is not None
    assert result.habit.start_time == time(21, 0)
    assert result.habit.end_time == time(21, 15)
