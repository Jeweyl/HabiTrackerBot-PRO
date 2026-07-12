"""Read-only statistics endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_session
from src.api.schemas import (
    DailyPointResponse,
    DailySeriesResponse,
    HabitBreakdownItemResponse,
    HabitBreakdownResponse,
    OverviewResponse,
    ScheduleItemResponse,
    ScheduleResponse,
)

from src.db.models import User
from src.services import stats_service

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


def _http_422(message: str) -> HTTPException:
    # Numeric 422 avoids Starlette's deprecated constant name churn.
    return HTTPException(status_code=422, detail=message)


@router.get(
    "/overview",
    response_model=OverviewResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def stats_overview(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: int = Query(default=7, ge=1, le=stats_service.MAX_STATS_RANGE_DAYS),
) -> OverviewResponse:
    """Aggregate completion stats for the last *days* (including today)."""
    try:
        overview = await stats_service.get_overview(session, user.id, days=days)
    except ValueError as exc:
        raise _http_422(str(exc)) from exc

    return OverviewResponse(
        days=overview.days,
        **{
            "from": overview.from_date,
            "to": overview.to_date,
            "total_tasks": overview.total_tasks,
            "completed_tasks": overview.completed_tasks,
            "missed_tasks": overview.missed_tasks,
            "completion_rate": overview.completion_rate,
            "streak": overview.streak,
            "habits_count": overview.habits_count,
        },
    )


@router.get(
    "/daily",
    response_model=DailySeriesResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def stats_daily(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
) -> DailySeriesResponse:
    """Daily series with gap-filled zeros for empty days."""
    try:
        series = await stats_service.get_daily_series(
            session, user.id, from_date, to_date
        )
    except ValueError as exc:
        raise _http_422(str(exc)) from exc

    return DailySeriesResponse(
        **{
            "from": from_date,
            "to": to_date,
            "series": [
                DailyPointResponse(
                    date=p.date,
                    total=p.total,
                    completed=p.completed,
                    missed=p.missed,
                )
                for p in series
            ],
        }
    )


@router.get(
    "/schedule",
    response_model=ScheduleResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def stats_schedule(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
) -> ScheduleResponse:
    """Tasks in the inclusive date range (empty list if none)."""
    try:
        items = await stats_service.get_schedule(session, user.id, from_date, to_date)
    except ValueError as exc:
        raise _http_422(str(exc)) from exc

    return ScheduleResponse(
        **{
            "from": from_date,
            "to": to_date,
            "items": [
                ScheduleItemResponse(
                    id=i.id,
                    title=i.title,
                    date=i.date,
                    start_time=i.start_time,
                    end_time=i.end_time,
                    is_completed=i.is_completed,
                    is_placeholder=i.is_placeholder,
                    habit_id=i.habit_id,
                )
                for i in items
            ],
        }
    )


@router.get(
    "/habits",
    response_model=HabitBreakdownResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def stats_habits(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: int = Query(default=7, ge=1, le=stats_service.MAX_STATS_RANGE_DAYS),
) -> HabitBreakdownResponse:
    """Per-habit completion breakdown for the last *days* (including today)."""
    try:
        items = await stats_service.get_habit_breakdown(session, user.id, days=days)
        overview = await stats_service.get_overview(session, user.id, days=days)
    except ValueError as exc:
        raise _http_422(str(exc)) from exc

    return HabitBreakdownResponse(
        days=days,
        **{
            "from": overview.from_date,
            "to": overview.to_date,
            "items": [
                HabitBreakdownItemResponse(
                    habit_id=i.habit_id,
                    title=i.title,
                    total=i.total,
                    completed=i.completed,
                    missed=i.missed,
                    completion_rate=i.completion_rate,
                )
                for i in items
            ],
        },
    )
