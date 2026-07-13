"""Pydantic request/response models for the stats API."""

from __future__ import annotations

import datetime
from typing import Optional

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
    from_: datetime.date = Field(alias="from")
    to: datetime.date
    total_tasks: int
    completed_tasks: int
    missed_tasks: int
    completion_rate: float
    streak: int
    habits_count: int
    language: str = "ru"

    model_config = {"populate_by_name": True}



class DailyPointResponse(BaseModel):
    """One day in the daily series."""

    date: datetime.date
    total: int
    completed: int
    missed: int


class DailySeriesResponse(BaseModel):
    """Gap-filled daily completion series."""

    from_: datetime.date = Field(alias="from")
    to: datetime.date
    series: list[DailyPointResponse]

    model_config = {"populate_by_name": True}


class ScheduleItemResponse(BaseModel):
    """Task row for schedule/calendar."""

    id: int
    title: str
    date: datetime.date
    start_time: str
    end_time: str | None
    is_completed: bool
    is_placeholder: bool
    habit_id: int | None


class ScheduleResponse(BaseModel):
    """Tasks in a date range."""

    from_: datetime.date = Field(alias="from")
    to: datetime.date
    items: list[ScheduleItemResponse]

    model_config = {"populate_by_name": True}


class HabitBreakdownItemResponse(BaseModel):
    """One habit in the breakdown list."""

    habit_id: int
    title: str
    total: int
    completed: int
    missed: int
    completion_rate: float


class HabitBreakdownResponse(BaseModel):
    """Per-habit stats for a rolling window."""

    days: int
    from_: datetime.date = Field(alias="from")
    to: datetime.date
    items: list[HabitBreakdownItemResponse]

    model_config = {"populate_by_name": True}


class HealthResponse(BaseModel):
    """Liveness probe."""

    status: str = "ok"


class MeResponse(BaseModel):
    """Authenticated user profile + account settings."""

    id: int
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language: str
    timezone: str
    reminder_time: str | None = None
    check_interval: int


class MeUpdateRequest(BaseModel):
    """Partial account settings update (omit = leave unchanged).

    ``reminder_time`` may be set to ``null`` explicitly to disable reminders.
    """

    language: Optional[str] = None
    timezone: Optional[str] = None
    reminder_time: Optional[str] = Field(
        default=None,
        description="HH:MM or null to disable; omit field to leave unchanged",
    )
    check_interval: Optional[int] = None

    model_config = {"extra": "forbid"}


class TaskResponse(BaseModel):
    """Single task for dashboard CRUD."""

    id: int
    title: str
    date: datetime.date
    start_time: str
    end_time: str | None
    is_completed: bool
    is_placeholder: bool
    habit_id: int | None


class TaskListResponse(BaseModel):
    """Tasks in a date range."""

    from_: datetime.date = Field(alias="from")
    to: datetime.date
    items: list[TaskResponse]

    model_config = {"populate_by_name": True}


class TaskCreateRequest(BaseModel):
    """Create a one-off (or schedule) task."""

    title: str = Field(..., min_length=1, max_length=200)
    date: datetime.date
    start_time: str = Field(..., description="HH:MM on 15-minute grid")
    end_time: Optional[str] = Field(
        default=None, description="HH:MM or null for open-ended"
    )

    model_config = {"extra": "forbid"}


class TaskUpdateRequest(BaseModel):
    """Partial task update. Omitted fields unchanged.

    To clear end_time (open-ended), send ``\"end_time\": null`` explicitly.
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    # Use datetime.date — field name ``date`` would shadow ``from datetime import date``.
    date: Optional[datetime.date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_completed: Optional[bool] = None

    model_config = {"extra": "forbid"}




