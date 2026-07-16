"""Background reminder delivery for users with configured reminder_time."""

import logging

from aiogram import Bot
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db
from src.i18n import normalize_lang, t
from src.utils.timezone import local_now


logger = logging.getLogger(__name__)


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

            user_local = local_now(user.timezone)
            local_date = user_local.date()
            local_time = user_local.time().replace(second=0, microsecond=0)
            reminder = user.reminder_time.replace(second=0, microsecond=0)

            if local_time < reminder:
                continue
            if user.last_reminder_date == local_date:
                continue

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=t("reminder.text", normalize_lang(user.language)),
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
