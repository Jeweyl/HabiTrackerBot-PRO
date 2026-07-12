"""Background check-in notifications for incomplete due tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

from aiogram import Bot
from sqlalchemy import select

from src.db.models import Task, User

from src.db.session import get_db
from src.i18n import normalize_lang, t
from src.keyboards.inline import get_checkin_keyboard
from src.utils.timezone import local_now


logger = logging.getLogger(__name__)


class _CheckinTaskLike(Protocol):
    """Minimal task shape used by pure eligibility checks."""

    date: object
    start_time: object
    is_completed: bool
    is_placeholder: bool
    last_checkin_at: datetime | None


def is_checkin_due(
    task: _CheckinTaskLike,
    *,
    local_dt: datetime,
    interval_minutes: int,
) -> bool:
    """Return whether a task should receive a check-in notification.

    Rules:
    - ``interval_minutes <= 0`` disables check-ins
    - completed / placeholder tasks are skipped
    - only tasks scheduled for the user's local today
    - local time must be at/after ``start_time``
    - first check-in is sent immediately after start_time
    - subsequent check-ins respect ``interval_minutes`` anti-spam
    """
    if interval_minutes is None or interval_minutes <= 0:
        return False
    if task.is_completed or task.is_placeholder:
        return False
    if task.date != local_dt.date():
        return False

    local_time = local_dt.time().replace(second=0, microsecond=0)
    start = task.start_time.replace(second=0, microsecond=0)  # type: ignore[union-attr]
    if local_time < start:
        return False

    if task.last_checkin_at is None:
        return True

    last = task.last_checkin_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    # Compare in the same timezone as local_dt for stable interval math.
    last_local = last.astimezone(local_dt.tzinfo) if local_dt.tzinfo else last
    return (local_dt - last_local) >= timedelta(minutes=interval_minutes)


def _checkin_text(title: str, lang: str = "ru") -> str:
    """Build the check-in prompt text for a task title."""
    return t("checkin.prompt", normalize_lang(lang), title=title)



async def process_checkins(bot: Bot) -> int:
    """Send due check-in prompts and return the number of messages sent.

    Independent of daily ``reminder_time``. Uses each user's
    ``check_interval`` and local timezone. Telegram delivery failures are
    logged and skipped without aborting the batch.
    """
    sent = 0

    async with get_db() as session:
        result = await session.execute(
            select(User).where(User.check_interval > 0)
        )
        users = result.scalars().all()

        for user in users:
            interval = user.check_interval
            if interval is None or interval <= 0:
                continue

            try:
                user_local = local_now(user.timezone)
            except Exception:
                logger.warning(
                    "Failed to resolve timezone for user_id=%s tz=%s",
                    user.id,
                    user.timezone,
                    exc_info=True,
                )
                continue

            local_date = user_local.date()

            tasks_result = await session.execute(
                select(Task).where(
                    Task.user_id == user.id,
                    Task.date == local_date,
                    Task.is_completed.is_(False),
                    Task.is_placeholder.is_(False),
                )
            )
            tasks = tasks_result.scalars().all()

            for task in tasks:
                if not is_checkin_due(
                    task,
                    local_dt=user_local,
                    interval_minutes=interval,
                ):
                    continue

                try:
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=_checkin_text(task.title, user.language),
                        reply_markup=get_checkin_keyboard(task.id),
                    )

                except Exception as exc:
                    logger.warning(
                        "Failed to send check-in to telegram_id=%s task_id=%s: %s",
                        user.telegram_id,
                        task.id,
                        exc,
                    )
                    continue

                # Stamp anti-spam only after a successful send.
                task.last_checkin_at = datetime.now(timezone.utc)
                sent += 1

        if sent:
            await session.commit()

    if sent:
        logger.info("Sent %d check-in(s)", sent)
    return sent
