"""Handlers for check-in notification callbacks (yes / no)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from src.db.models import Task, User
from src.db.session import get_db
from src.i18n import normalize_lang, t

logger = logging.getLogger(__name__)

router = Router()
"""Router for check-in yes/no callbacks."""


async def _get_user(telegram_id: int, session) -> User | None:
    """Look up the user by Telegram ID."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


@router.callback_query(F.data.startswith("checkin:yes:"))
async def checkin_yes(callback: CallbackQuery) -> None:
    """Mark the task completed after a positive check-in answer."""
    try:
        task_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user = await _get_user(callback.from_user.id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return

        lang = normalize_lang(user.language)
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user.id:
            await callback.answer(
                t("checkin.task_not_found", lang),
                show_alert=True,
            )
            return

        task.is_completed = True
        await session.commit()
        title = task.title

    await callback.answer(t("checkin.yes_toast", lang))
    try:
        await callback.message.edit_text(
            t("checkin.yes_ack", lang, title=title)
        )
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
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user = await _get_user(callback.from_user.id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return

        lang = normalize_lang(user.language)
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user.id:
            await callback.answer(
                t("checkin.task_not_found", lang),
                show_alert=True,
            )
            return

        # Explicitly leave incomplete; do not touch last_checkin_at.
        title = task.title
        is_completed = task.is_completed

    await callback.answer(t("checkin.no_toast", lang))
    try:
        status = (
            t("checkin.status_done", lang)
            if is_completed
            else t("checkin.status_pending", lang)
        )
        await callback.message.edit_text(
            t("checkin.no_ack", lang, title=title, status=status)
        )
    except Exception:
        logger.warning(
            "Could not edit check-in message after no for task_id=%s",
            task_id,
            exc_info=True,
        )
