"""Pydantic request/response models for the stats API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class TokenExchangeRequest(BaseModel):
    """Body for one-time token → JWT exchange."""

    token: str = Field(..., min_length=1)


class TokenExchangeResponse(BaseModel):
    """JWT access token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class OverviewResponse(BaseModel):
    """Aggregate stats for a rolling window."""

    days: int
    from_: date = Field(alias="from")
    to: date
    total_tasks: int
    completed_tasks: int
    missed_tasks: int
    completion_rate: float
    streak: int
    habits_count: int

    model_config = {"populate_by_name": True}


class DailyPointResponse(BaseModel):
    """One day in the daily series."""

    date: date
    total: int
    completed: int
    missed: int


class DailySeriesResponse(BaseModel):
    """Gap-filled daily completion series."""

    from_: date = Field(alias="from")
    to: date
    series: list[DailyPointResponse]

    model_config = {"populate_by_name": True}


class ScheduleItemResponse(BaseModel):
    """Task row for schedule/calendar."""

    id: int
    title: str
    date: date
    start_time: str
    end_time: str | None
    is_completed: bool
    is_placeholder: bool
    habit_id: int | None


class ScheduleResponse(BaseModel):
    """Tasks in a date range."""

    from_: date = Field(alias="from")
    to: date
    items: list[ScheduleItemResponse]

    model_config = {"populate_by_name": True}


class HealthResponse(BaseModel):
    """Liveness probe."""

    status: str = "ok"
