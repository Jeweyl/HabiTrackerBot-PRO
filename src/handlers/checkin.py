"""Handlers for check-in notification callbacks."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from src.db.models import Task, User
from src.db.session import get_db
from src.i18n import normalize_lang, t
from src.keyboards.inline import (
    get_checkin_keyboard,
    get_checkin_reschedule_keyboard,
    get_checkin_snooze_keyboard,
)
from src.utils.conflict import is_time_slot_free
from src.utils.free_slots import (
    end_of_local_day_utc,
    find_free_slots,
    shift_end_time,
    task_duration_minutes,
)
from src.utils.timezone import local_now

logger = logging.getLogger(__name__)

router = Router()
"""Router for check-in callbacks (yes / mute / later / reschedule)."""

_SNOOZE_ALLOWED = frozenset({15, 30, 45, 60})


async def _get_user(telegram_id: int, session) -> User | None:
    """Look up the user by Telegram ID."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


def _parse_task_id(data: str, index: int = 2) -> int | None:
    """Extract task_id from callback data at *index*, or None."""
    try:
        return int(data.split(":")[index])
    except (IndexError, ValueError):
        return None


async def _load_owned_task(
    callback: CallbackQuery,
    task_id: int,
    session,
) -> tuple[User | None, Task | None, str]:
    """Load user + owned task; return (user, task, lang)."""
    user = await _get_user(callback.from_user.id, session)
    if user is None:
        return None, None, "ru"
    lang = normalize_lang(user.language)
    task = await session.get(Task, task_id)
    if task is None or task.user_id != user.id:
        return user, None, lang
    return user, task, lang


async def _safe_edit(callback: CallbackQuery, text: str, **kwargs) -> None:
    """Edit the check-in message; log failures without raising."""
    try:
        await callback.message.edit_text(text, **kwargs)
    except Exception:
        logger.warning(
            "Could not edit check-in message: %s",
            text[:80],
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Yes — mark completed
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("checkin:yes:"))
async def checkin_yes(callback: CallbackQuery) -> None:
    """Mark the task completed after a positive check-in answer."""
    task_id = _parse_task_id(callback.data)
    if task_id is None:
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user, task, lang = await _load_owned_task(callback, task_id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return
        if task is None:
            await callback.answer(t("checkin.task_not_found", lang), show_alert=True)
            return

        task.is_completed = True
        await session.commit()
        title = task.title

    await callback.answer(t("checkin.yes_toast", lang))
    await _safe_edit(callback, t("checkin.yes_ack", lang, title=title))


# ---------------------------------------------------------------------------
# Mute — don't remind again today (and legacy checkin:no)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("checkin:mute:"))
@router.callback_query(F.data.startswith("checkin:no:"))
async def checkin_mute(callback: CallbackQuery) -> None:
    """Suppress further check-ins for this task until end of local day."""
    task_id = _parse_task_id(callback.data)
    if task_id is None:
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user, task, lang = await _load_owned_task(callback, task_id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return
        if task is None:
            await callback.answer(t("checkin.task_not_found", lang), show_alert=True)
            return

        try:
            user_local = local_now(user.timezone)
        except Exception:
            user_local = datetime.now(timezone.utc)

        task.checkin_snooze_until = end_of_local_day_utc(user_local)
        await session.commit()
        title = task.title

    await callback.answer(t("checkin.mute_toast", lang))
    await _safe_edit(callback, t("checkin.mute_ack", lang, title=title))


# ---------------------------------------------------------------------------
# Later — show snooze duration menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("checkin:later:"))
async def checkin_later(callback: CallbackQuery) -> None:
    """Show 15/30/45/60 minute snooze options."""
    task_id = _parse_task_id(callback.data)
    if task_id is None:
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user, task, lang = await _load_owned_task(callback, task_id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return
        if task is None:
            await callback.answer(t("checkin.task_not_found", lang), show_alert=True)
            return
        title = task.title

    await callback.answer()
    await _safe_edit(
        callback,
        t("checkin.choose_snooze", lang, title=title),
        reply_markup=get_checkin_snooze_keyboard(task_id, lang),
    )


# ---------------------------------------------------------------------------
# Snooze — set checkin_snooze_until = now + N minutes
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("checkin:snooze:"))
async def checkin_snooze(callback: CallbackQuery) -> None:
    """Snooze check-ins for the selected number of minutes."""
    parts = (callback.data or "").split(":")
    # checkin:snooze:{id}:{minutes}
    try:
        task_id = int(parts[2])
        minutes = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    if minutes not in _SNOOZE_ALLOWED:
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user, task, lang = await _load_owned_task(callback, task_id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return
        if task is None:
            await callback.answer(t("checkin.task_not_found", lang), show_alert=True)
            return

        task.checkin_snooze_until = datetime.now(timezone.utc) + timedelta(
            minutes=minutes
        )
        await session.commit()
        title = task.title

    await callback.answer(t("checkin.snooze_toast", lang, n=minutes))
    await _safe_edit(
        callback,
        t("checkin.snooze_ack", lang, title=title, n=minutes),
    )


# ---------------------------------------------------------------------------
# Reschedule — show free slots for today
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("checkin:reschedule:"))
async def checkin_reschedule(callback: CallbackQuery) -> None:
    """List future free slots on the current local day."""
    task_id = _parse_task_id(callback.data)
    if task_id is None:
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user, task, lang = await _load_owned_task(callback, task_id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return
        if task is None:
            await callback.answer(t("checkin.task_not_found", lang), show_alert=True)
            return

        title = task.title
        try:
            user_local = local_now(user.timezone)
        except Exception:
            user_local = datetime.now(timezone.utc)

        local_date = user_local.date()
        after = user_local.time().replace(second=0, microsecond=0)

        others = await session.execute(
            select(Task).where(
                Task.user_id == user.id,
                Task.date == local_date,
                Task.id != task.id,
            )
        )
        occupied = [
            (row.start_time, row.end_time) for row in others.scalars().all()
        ]
        duration = task_duration_minutes(task.start_time, task.end_time)
        slots = find_free_slots(
            occupied=occupied,
            duration_minutes=duration,
            after=after,
            day=local_date,
        )

    await callback.answer()
    if not slots:
        await _safe_edit(
            callback,
            t("checkin.no_free_slots", lang, title=title),
            reply_markup=get_checkin_keyboard(task_id, lang),
        )
        return

    await _safe_edit(
        callback,
        t("checkin.choose_slot", lang, title=title),
        reply_markup=get_checkin_reschedule_keyboard(task_id, slots, lang),
    )


# ---------------------------------------------------------------------------
# Move — apply selected free slot
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("checkin:move:"))
async def checkin_move(callback: CallbackQuery) -> None:
    """Move the task to the selected free start time (same day)."""
    parts = (callback.data or "").split(":")
    # checkin:move:{id}:{HH}:{MM}
    try:
        task_id = int(parts[2])
        hour = int(parts[3])
        minute = int(parts[4])
        new_start = time(hour, minute)
    except (IndexError, ValueError):
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user, task, lang = await _load_owned_task(callback, task_id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return
        if task is None:
            await callback.answer(t("checkin.task_not_found", lang), show_alert=True)
            return

        new_end = shift_end_time(task.start_time, task.end_time, new_start)

        free = await is_time_slot_free(
            session,
            user.id,
            task.date,
            new_start,
            new_end,
            exclude_task_id=task.id,
        )
        if not free:
            # Slot taken since the menu was shown — re-offer free slots.
            title = task.title
            try:
                user_local = local_now(user.timezone)
            except Exception:
                user_local = datetime.now(timezone.utc)
            after = user_local.time().replace(second=0, microsecond=0)
            others = await session.execute(
                select(Task).where(
                    Task.user_id == user.id,
                    Task.date == task.date,
                    Task.id != task.id,
                )
            )
            occupied = [
                (row.start_time, row.end_time) for row in others.scalars().all()
            ]
            duration = task_duration_minutes(task.start_time, task.end_time)
            slots = find_free_slots(
                occupied=occupied,
                duration_minutes=duration,
                after=after,
                day=task.date,
            )
            await callback.answer(t("checkin.invalid", lang), show_alert=True)
            if not slots:
                await _safe_edit(
                    callback,
                    t("checkin.no_free_slots", lang, title=title),
                    reply_markup=get_checkin_keyboard(task_id, lang),
                )
            else:
                await _safe_edit(
                    callback,
                    t("checkin.choose_slot", lang, title=title),
                    reply_markup=get_checkin_reschedule_keyboard(
                        task_id, slots, lang
                    ),
                )
            return

        task.start_time = new_start
        task.end_time = new_end
        # Allow a fresh check-in cycle after the new start time.
        task.last_checkin_at = None
        task.checkin_snooze_until = None
        await session.commit()
        title = task.title
        time_label = new_start.strftime("%H:%M")

    await callback.answer(t("checkin.moved_toast", lang, time=time_label))
    await _safe_edit(
        callback,
        t("checkin.moved_ack", lang, title=title, time=time_label),
    )


# ---------------------------------------------------------------------------
# Back — return to main check-in prompt
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("checkin:back:"))
async def checkin_back(callback: CallbackQuery) -> None:
    """Return from snooze/reschedule submenu to the main check-in prompt."""
    task_id = _parse_task_id(callback.data)
    if task_id is None:
        await callback.answer(t("checkin.invalid", "ru"), show_alert=True)
        return

    async with get_db() as session:
        user, task, lang = await _load_owned_task(callback, task_id, session)
        if user is None:
            await callback.answer(t("checkin.user_not_found", "ru"), show_alert=True)
            return
        if task is None:
            await callback.answer(t("checkin.task_not_found", lang), show_alert=True)
            return
        title = task.title

    await callback.answer()
    await _safe_edit(
        callback,
        t("checkin.prompt", lang, title=title),
        reply_markup=get_checkin_keyboard(task_id, lang),
    )
