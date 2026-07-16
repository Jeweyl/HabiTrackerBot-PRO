"""Habit CRUD for the authenticated dashboard user."""

from __future__ import annotations

from datetime import date, time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_session
from src.api.schemas import (
    HabitCreateRequest,
    HabitListResponse,
    HabitResponse,
    HabitUpdateRequest,
)
from src.db.models import Habit, Task, User
from src.services.habit_generator import generate_tasks_for_habit
from src.utils.conflict import check_habit_conflicts

router = APIRouter(prefix="/api/v1/habits", tags=["habits"])

_GRID_MINUTES = frozenset({0, 15, 30, 45})
_ALLOWED_FREQUENCIES = frozenset({"daily", "weekdays", "weekends"})


def _http_422(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _http_409(message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": message, "code": "habit_conflict"},
    )


def _http_404() -> HTTPException:
    return HTTPException(status_code=404, detail="Habit not found")


def _parse_hh_mm(raw: str, *, field: str = "time") -> time:
    text = (raw or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field} must be HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{field} must be HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{field} must be a valid clock time")
    if minute not in _GRID_MINUTES:
        raise ValueError(f"{field} must use 15-minute grid (00/15/30/45)")
    return time(hour, minute)


def _normalize_frequency(raw: str) -> str:
    freq = (raw or "").strip().lower()
    if freq not in _ALLOWED_FREQUENCIES:
        raise ValueError("frequency must be daily, weekdays, or weekends")
    return freq


def _habit_to_response(habit: Habit) -> HabitResponse:
    end = habit.end_time.strftime("%H:%M") if habit.end_time is not None else None
    return HabitResponse(
        id=habit.id,
        title=habit.title,
        start_time=habit.start_time.strftime("%H:%M"),
        end_time=end,
        frequency=habit.frequency or "daily",
    )


async def _get_owned_habit(
    session: AsyncSession, user_id: int, habit_id: int
) -> Habit:
    result = await session.execute(
        select(Habit).where(Habit.id == habit_id, Habit.user_id == user_id)
    )
    habit = result.scalar_one_or_none()
    if habit is None:
        raise _http_404()
    return habit


async def _regenerate_habit_tasks(session: AsyncSession, habit_id: int) -> None:
    """Drop future incomplete habit tasks and regenerate from the template.

    Keeps completed tasks (history) and past incomplete tasks as-is.
    """
    today = date.today()
    await session.execute(
        delete(Task).where(
            Task.habit_id == habit_id,
            Task.date >= today,
            Task.is_completed.is_(False),
        )
    )
    await session.flush()
    await generate_tasks_for_habit(habit_id, session=session)


@router.get(
    "",
    response_model=HabitListResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def list_habits(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HabitListResponse:
    """List all habits for the current user."""
    result = await session.execute(
        select(Habit).where(Habit.user_id == user.id).order_by(Habit.id)
    )
    habits = result.scalars().all()
    return HabitListResponse(items=[_habit_to_response(h) for h in habits])


@router.post(
    "",
    response_model=HabitResponse,
    status_code=201,
    responses={
        401: {"description": "Unauthorized"},
        409: {"description": "Habit time/frequency conflict"},
        422: {"description": "Validation error"},
    },
)
async def create_habit(
    body: HabitCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HabitResponse:
    """Create a habit template and generate upcoming tasks."""
    title = body.title.strip()
    if not title:
        raise _http_422("title must not be empty")

    try:
        start = _parse_hh_mm(body.start_time, field="start_time")
        if body.end_time is None or str(body.end_time).strip() == "":
            end: time | None = None
        else:
            end = _parse_hh_mm(body.end_time, field="end_time")
        frequency = _normalize_frequency(body.frequency)
    except ValueError as exc:
        raise _http_422(str(exc)) from exc

    if end is not None and end <= start:
        raise _http_422("end_time must be after start_time")

    conflicting = await check_habit_conflicts(
        session, user.id, start, end, frequency
    )
    if conflicting:
        raise _http_409("Habit conflicts with an existing habit")

    habit = Habit(
        user_id=user.id,
        title=title,
        start_time=start,
        end_time=end,
        frequency=frequency,
    )
    session.add(habit)
    await session.flush()
    await session.refresh(habit)

    await generate_tasks_for_habit(habit.id, session=session)
    return _habit_to_response(habit)


@router.get(
    "/{habit_id}",
    response_model=HabitResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
    },
)
async def get_habit(
    habit_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HabitResponse:
    """Return one owned habit."""
    habit = await _get_owned_habit(session, user.id, habit_id)
    return _habit_to_response(habit)


@router.patch(
    "/{habit_id}",
    response_model=HabitResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        409: {"description": "Habit time/frequency conflict"},
        422: {"description": "Validation error"},
    },
)
async def patch_habit(
    habit_id: int,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HabitResponse:
    """Partially update a habit. Explicit ``end_time: null`` clears end time."""
    try:
        raw: Any = await request.json()
    except Exception as exc:
        raise _http_422("Invalid JSON body") from exc

    if raw is None or not isinstance(raw, dict):
        raise _http_422("Body must be a JSON object")

    end_provided = "end_time" in raw

    try:
        body = HabitUpdateRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    habit = await _get_owned_habit(session, user.id, habit_id)

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise _http_422("title must not be empty")
        habit.title = title

    schedule_touched = (
        body.start_time is not None
        or end_provided
        or body.frequency is not None
        or body.title is not None
    )

    if body.start_time is not None:
        try:
            new_start = _parse_hh_mm(body.start_time, field="start_time")
        except ValueError as exc:
            raise _http_422(str(exc)) from exc
    else:
        new_start = habit.start_time

    if end_provided:
        if body.end_time is None or (
            isinstance(body.end_time, str) and not body.end_time.strip()
        ):
            new_end: time | None = None
        else:
            try:
                new_end = _parse_hh_mm(str(body.end_time), field="end_time")
            except ValueError as exc:
                raise _http_422(str(exc)) from exc
    else:
        new_end = habit.end_time

    if body.frequency is not None:
        try:
            new_freq = _normalize_frequency(body.frequency)
        except ValueError as exc:
            raise _http_422(str(exc)) from exc
    else:
        new_freq = habit.frequency or "daily"

    if new_end is not None and new_end <= new_start:
        raise _http_422("end_time must be after start_time")

    if (
        body.start_time is not None
        or end_provided
        or body.frequency is not None
    ):
        conflicting = await check_habit_conflicts(
            session,
            user.id,
            new_start,
            new_end,
            new_freq,
            exclude_habit_id=habit.id,
        )
        if conflicting:
            raise _http_409("Habit conflicts with an existing habit")
        habit.start_time = new_start
        habit.end_time = new_end
        habit.frequency = new_freq

    session.add(habit)
    await session.flush()
    await session.refresh(habit)

    if schedule_touched:
        await _regenerate_habit_tasks(session, habit.id)

    return _habit_to_response(habit)


@router.delete(
    "/{habit_id}",
    status_code=204,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
    },
)
async def delete_habit(
    habit_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete an owned habit (CASCADE removes linked tasks)."""
    habit = await _get_owned_habit(session, user.id, habit_id)
    await session.delete(habit)
    await session.flush()
