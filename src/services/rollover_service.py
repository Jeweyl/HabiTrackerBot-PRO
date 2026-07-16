"""Background auto-rollover of incomplete tasks to the next local day."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from src.db.models import Task, User
from src.db.session import get_db
from src.utils.timezone import local_now


logger = logging.getLogger(__name__)


async def process_rollovers() -> int:
    """Shift incomplete auto-rollover tasks whose date is before local today.

    Rules:
    - only ``auto_rollover=True`` and ``is_completed=False``
    - skip placeholders
    - ``task.date`` is advanced by one day until it reaches the user's
      local today (covers multi-day downtime)
    - check-in anti-spam fields are cleared so a fresh cycle can start

    Returns:
        Number of tasks whose date was updated.
    """
    moved = 0

    async with get_db() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

        for user in users:
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

            local_today = user_local.date()

            tasks_result = await session.execute(
                select(Task).where(
                    Task.user_id == user.id,
                    Task.auto_rollover.is_(True),
                    Task.is_completed.is_(False),
                    Task.is_placeholder.is_(False),
                    Task.date < local_today,
                )
            )
            tasks = tasks_result.scalars().all()

            for task in tasks:
                # Catch up if the bot was offline for several days.
                while task.date < local_today:
                    task.date = task.date + timedelta(days=1)
                task.last_checkin_at = None
                task.checkin_snooze_until = None
                moved += 1

        if moved:
            await session.commit()

    if moved:
        logger.info("Rolled over %d incomplete task(s)", moved)
    return moved
