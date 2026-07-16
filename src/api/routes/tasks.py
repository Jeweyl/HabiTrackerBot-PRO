"""Task CRUD for the authenticated dashboard user."""

from __future__ import annotations

from datetime import date, time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_session
from src.api.schemas import (
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
    TaskUpdateRequest,
)
from src.db.models import Task, User
from src.services import stats_service
from src.utils.conflict import is_time_slot_free

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

_GRID_MINUTES = frozenset({0, 15, 30, 45})


def _http_422(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _http_409(message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": message, "code": "time_conflict"},
    )


def _http_404() -> HTTPException:
    return HTTPException(status_code=404, detail="Task not found")


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


def _task_to_response(task: Task) -> TaskResponse:
    start = (
        task.start_time.strftime("%H:%M") if task.start_time is not None else None
    )
    end = task.end_time.strftime("%H:%M") if task.end_time is not None else None
    return TaskResponse(
        id=task.id,
        title=task.title,
        date=task.date,
        start_time=start,
        end_time=end,
        is_completed=bool(task.is_completed),
        is_placeholder=bool(task.is_placeholder),
        habit_id=task.habit_id,
        auto_rollover=bool(getattr(task, "auto_rollover", False)),
    )


async def _get_owned_task(
    session: AsyncSession, user_id: int, task_id: int
) -> Task:
    result = await session.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise _http_404()
    return task


@router.get(
    "",
    response_model=TaskListResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def list_tasks(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
) -> TaskListResponse:
    """List the current user's tasks in an inclusive date range."""
    try:
        items = await stats_service.get_schedule(
            session, user.id, from_date, to_date
        )
    except ValueError as exc:
        raise _http_422(str(exc)) from exc

    return TaskListResponse(
        **{
            "from": from_date,
            "to": to_date,
            "items": [
                TaskResponse(
                    id=i.id,
                    title=i.title,
                    date=i.date,
                    start_time=i.start_time,
                    end_time=i.end_time,
                    is_completed=i.is_completed,
                    is_placeholder=i.is_placeholder,
                    habit_id=i.habit_id,
                    auto_rollover=bool(getattr(i, "auto_rollover", False)),
                )
                for i in items
            ],
        }
    )


@router.post(
    "",
    response_model=TaskResponse,
    status_code=201,
    responses={
        401: {"description": "Unauthorized"},
        409: {"description": "Time conflict"},
        422: {"description": "Validation error"},
    },
)
async def create_task(
    body: TaskCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskResponse:
    """Create a task; 409 if the time slot overlaps an existing task."""
    title = body.title.strip()
    if not title:
        raise _http_422("title must not be empty")

    try:
        if body.start_time is None or str(body.start_time).strip() == "":
            start = None
        else:
            start = _parse_hh_mm(body.start_time, field="start_time")
        end: time | None
        if body.end_time is None or str(body.end_time).strip() == "":
            end = None
        else:
            end = _parse_hh_mm(body.end_time, field="end_time")
    except ValueError as exc:
        raise _http_422(str(exc)) from exc

    if start is None:
        end = None
    elif end is not None and end <= start:
        raise _http_422("end_time must be after start_time")

    if start is not None:
        free = await is_time_slot_free(
            session, user.id, body.date, start, end
        )
        if not free:
            raise _http_409("Time slot conflicts with an existing task")

    task = Task(
        user_id=user.id,
        habit_id=None,
        title=title,
        date=body.date,
        start_time=start,
        end_time=end,
        is_completed=False,
        is_placeholder=False,
        auto_rollover=bool(body.auto_rollover),
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return _task_to_response(task)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    responses={401: {"description": "Unauthorized"}, 404: {"description": "Not found"}},
)
async def get_task(
    task_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskResponse:
    """Return one owned task."""
    task = await _get_owned_task(session, user.id, task_id)
    return _task_to_response(task)


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        409: {"description": "Time conflict"},
        422: {"description": "Validation error"},
    },
)
async def patch_task(
    task_id: int,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskResponse:
    """Partially update a task. Explicit ``end_time: null`` clears end time."""
    try:
        raw: Any = await request.json()
    except Exception as exc:
        raise _http_422("Invalid JSON body") from exc

    if raw is None or not isinstance(raw, dict):
        raise _http_422("Body must be a JSON object")

    end_provided = "end_time" in raw
    start_provided = "start_time" in raw

    try:
        body = TaskUpdateRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    task = await _get_owned_task(session, user.id, task_id)

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise _http_422("title must not be empty")
        task.title = title

    if body.is_completed is not None:
        task.is_completed = bool(body.is_completed)

    if body.auto_rollover is not None:
        task.auto_rollover = bool(body.auto_rollover)

    schedule_touched = (
        body.date is not None
        or start_provided
        or end_provided
    )

    new_date = body.date if body.date is not None else task.date

    if start_provided:
        if body.start_time is None or (
            isinstance(body.start_time, str) and not body.start_time.strip()
        ):
            new_start = None
        else:
            try:
                new_start = _parse_hh_mm(str(body.start_time), field="start_time")
            except ValueError as exc:
                raise _http_422(str(exc)) from exc
    else:
        new_start = task.start_time

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
        new_end = task.end_time

    if new_start is None:
        new_end = None
    elif new_end is not None and new_end <= new_start:
        raise _http_422("end_time must be after start_time")

    if schedule_touched:
        if new_start is not None:
            free = await is_time_slot_free(
                session,
                user.id,
                new_date,
                new_start,
                new_end,
                exclude_task_id=task.id,
            )
            if not free:
                raise _http_409("Time slot conflicts with an existing task")
        task.date = new_date
        task.start_time = new_start
        task.end_time = new_end

    session.add(task)
    await session.flush()
    await session.refresh(task)
    return _task_to_response(task)


@router.delete(
    "/{task_id}",
    status_code=204,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
    },
)
async def delete_task(
    task_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete an owned task."""
    task = await _get_owned_task(session, user.id, task_id)
    await session.delete(task)
    await session.flush()
