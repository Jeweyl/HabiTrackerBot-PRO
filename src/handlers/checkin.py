"""Handlers for check-in notification callbacks (yes / no)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from src.db.models import Task, User
from src.db.session import get_db

logger = logging.getLogger(__name__)

router = Router()
"""Router for check-in yes/no callbacks."""


async def _get_user_id(telegram_id: int, session) -> int | None:
    """Look up the internal user ID by Telegram ID."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    return user.id if user else None


@router.callback_query(F.data.startswith("checkin:yes:"))
async def checkin_yes(callback: CallbackQuery) -> None:
    """Mark the task completed after a positive check-in answer."""
    try:
        task_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.answer("Пользователь не найден.", show_alert=True)
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer(
                "⛔ Задача не найдена или недоступна.",
                show_alert=True,
            )
            return

        task.is_completed = True
        await session.commit()
        title = task.title

    await callback.answer("✅ Отмечено выполненным")
    try:
        await callback.message.edit_text(f'✅ «{title}» отмечено выполненным.')
    except Exception:
        logger.warning(
            "Could not edit check-in message after yes for task_id=%s",
            task_id,
            exc_info=True,
        )


@router.callback_query(F.data.startswith("checkin:no:"))
async def checkin_no(callback: CallbackQuery) -> None:
    """Acknowledge a negative check-in without completing the task.

    Anti-spam is already enforced via ``Task.last_checkin_at`` set when the
    prompt was sent, so the next prompt will not arrive before the interval.
    """
    try:
        task_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.answer("Пользователь не найден.", show_alert=True)
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer(
                "⛔ Задача не найдена или недоступна.",
                show_alert=True,
            )
            return

        # Explicitly leave incomplete; do not touch last_checkin_at.
        title = task.title
        is_completed = task.is_completed

    await callback.answer("Ок, напомним позже")
    try:
        status = "уже выполнено" if is_completed else "пока не выполнено"
        await callback.message.edit_text(
            f'❌ «{title}» — {status}. Напомним позже.'
        )
    except Exception:
        logger.warning(
            "Could not edit check-in message after no for task_id=%s",
            task_id,
            exc_info=True,
        )
