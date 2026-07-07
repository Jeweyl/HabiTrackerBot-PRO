"""SQLAlchemy ORM models for the application database."""

from datetime import date, datetime, time, timezone
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Time, false, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class User(Base):
    """Telegram user model.

    Attributes:
        id: Primary key, auto-incremented integer.
        telegram_id: Unique Telegram user identifier.
        language: User's preferred language (default 'ru').
        timezone: User's timezone string (default 'UTC').
        created_at: Timestamp of record creation.
        updated_at: Timestamp of last update.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(10), default="ru", server_default="ru")
    timezone: Mapped[str] = mapped_column(
        String(50), default="UTC", server_default="UTC"
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
        start_time: Start time of the task.
        end_time: End time of the task (optional — ``None`` means open-ended).
        is_completed: Whether the task has been marked as done.
        is_placeholder: Whether this is a placeholder task (ЗАНЯТ).
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
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    is_completed: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_placeholder: Mapped[bool] = mapped_column(default=False, server_default=false())
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
