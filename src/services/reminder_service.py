"""Background reminder delivery for users with configured reminder_time."""

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db

logger = logging.getLogger(__name__)


def _parse_timezone_offset(tz_value: str) -> timedelta:
    """Parse timezone values like ``UTC``, ``+3``, ``-5`` into a timedelta.

    Args:
        tz_value: Stored user timezone string.

    Returns:
        Timedelta offset from UTC.
    """
    if not tz_value or tz_value.upper() == "UTC":
        return timedelta(0)

    value = tz_value.strip()
    if value.upper().startswith("UTC"):
        value = value[3:]

    if not value or value in {"0", "+0", "-0"}:
        return timedelta(0)

    try:
        hours = int(value)
    except ValueError:
        logger.warning("Unknown timezone value '%s', falling back to UTC", tz_value)
        return timedelta(0)

    return timedelta(hours=hours)


def _local_now(tz_value: str) -> datetime:
    """Return current local datetime for the given timezone offset."""
    offset = _parse_timezone_offset(tz_value)
    return datetime.now(timezone.utc).astimezone(timezone(offset))


async def process_reminders(bot: Bot) -> int:
    """Send due daily reminders and return the number of messages sent.

    A reminder is sent when:
    - ``reminder_time`` is set
    - local time is at/after the configured hour:minute
    - no reminder was sent yet for the user's local date
    """
    sent = 0

    async with get_db() as session:
        result = await session.execute(
            select(User).where(User.reminder_time.is_not(None))
        )
        users = result.scalars().all()

        for user in users:
            if user.reminder_time is None:
                continue

            local_now = _local_now(user.timezone)
            local_date = local_now.date()
            local_time = local_now.time().replace(second=0, microsecond=0)
            reminder = user.reminder_time.replace(second=0, microsecond=0)

            if local_time < reminder:
                continue
            if user.last_reminder_date == local_date:
                continue

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        "⏰ Напоминание\n"
                        "Пора отметить привычки и задачи на сегодня.\n"
                        "Откройте бота и проверьте расписание."
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to send reminder to telegram_id=%s: %s",
                    user.telegram_id,
                    exc,
                )
                continue

            user.last_reminder_date = local_date
            sent += 1

        if sent:
            await session.commit()

    if sent:
        logger.info("Sent %d reminder(s)", sent)
    return sent
