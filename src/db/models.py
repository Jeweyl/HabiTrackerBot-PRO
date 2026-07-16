"""SQLAlchemy ORM models for the application database."""

from datetime import date, datetime, time, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Time,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class User(Base):
    """Telegram user model.

    Attributes:
        id: Primary key, auto-incremented integer.
        telegram_id: Unique Telegram user identifier.
        username: Telegram @username without the leading ``@`` (optional).
        first_name: Telegram first name (optional, almost always present).
        last_name: Telegram last name (optional).
        language: User's preferred language (default 'ru').
        timezone: User's timezone string (default 'UTC').
        reminder_time: Preferred daily reminder time (optional).
        check_interval: Reminder check interval in minutes.
        checkin_no_spam: If True, do not re-send check-ins when the user
            ignores the first prompt for a task today.
        ask_auto_rollover: If True, ask about auto-rollover after creating
            a task.
        last_reminder_date: Local date when the last reminder was sent.
        created_at: Timestamp of record creation.
        updated_at: Timestamp of last update.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="ru", server_default="ru")

    timezone: Mapped[str] = mapped_column(
        String(50), default="UTC", server_default="UTC"
    )
    reminder_time: Mapped[Optional[time]] = mapped_column(
        Time, nullable=True, default=None
    )
    check_interval: Mapped[int] = mapped_column(
        Integer, default=15, server_default="15"
    )
    checkin_no_spam: Mapped[bool] = mapped_column(
        default=True, server_default="true"
    )
    ask_auto_rollover: Mapped[bool] = mapped_column(
        default=False, server_default="false"
    )
    last_reminder_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, default=None
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class UserAIState(Base):
    """User AI assistant state model.

    Stores the last AI-generated SMART plan and a summarized history
    for each user who has interacted with the AI assistant.

    Attributes:
        id: Primary key, auto-incremented integer.
        user_id: Foreign key to the users table (unique, one state per user).
        summary: JSONB column containing the AI-generated SMART plan
            and a brief summarized interaction history.
        updated_at: Timestamp of the last state update.
    """

    __tablename__ = "user_ai_states"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    summary: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
        default={},
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class Task(Base):
    """User task model for schedule items on specific dates.

    Tasks can be created manually or generated from habits (future).
    Each task is tied to a specific date and time window.

    Attributes:
        id: Primary key, auto-incremented integer.
        user_id: Foreign key to the users table.
        habit_id: Foreign key to the habits table (optional — ``None`` when
            the task was created manually, not from a habit).
        title: Task description (1–200 characters).
        date: The date on which the task is scheduled.
        start_time: Start time of the task (``None`` = untimed todo, no check-ins).
        end_time: End time of the task (optional — ``None`` means open-ended).
        is_completed: Whether the task has been marked as done.
        is_placeholder: Whether this is a placeholder task (ЗАНЯТ).
        auto_rollover: If True and incomplete, shift ``date`` to the next day
            at local midnight.
        last_checkin_at: UTC timestamp of the last check-in prompt (anti-spam).
        checkin_snooze_until: UTC timestamp until which check-ins are suppressed
            (mute until end of day, or snooze for N minutes).
        created_at: Timestamp of record creation.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    habit_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("habits.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    is_completed: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_placeholder: Mapped[bool] = mapped_column(default=False, server_default=false())
    auto_rollover: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
    last_checkin_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    checkin_snooze_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class Habit(Base):
    """User habit model.

    Attributes:
        id: Primary key, auto-incremented integer.
        user_id: Foreign key to the users table.
        title: Habit name/title (1–200 characters).
        start_time: Daily start time for the habit.
        end_time: Daily end time for the habit (optional — ``None`` means no fixed end).
        frequency: Repeat frequency — ``daily``, ``weekdays``, or ``weekends``.
        created_at: Timestamp of record creation.
    """

    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    frequency: Mapped[str] = mapped_column(
        String(20), default="daily", server_default="daily"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
