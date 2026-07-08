"""Settings menu handlers for the Telegram bot."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db
from src.keyboards.inline import (
    get_check_interval_keyboard,
    get_language_keyboard,
    get_main_menu_keyboard,
    get_reminder_time_keyboard,
    get_settings_menu_keyboard,
    get_timezone_keyboard,
)
from src.states.fsm import MainFSM, SettingsFSM

logger = logging.getLogger(__name__)

router = Router()
"""Router for settings handlers."""


async def _get_user(session, telegram_id: int) -> User | None:
    """Look up a user by Telegram ID.

    Args:
        session: An active SQLAlchemy async session.
        telegram_id: The Telegram user identifier.

    Returns:
        The User instance or None.
    """
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# =============================================================================
# Entry point: main_menu -> settings menu
# =============================================================================


@router.callback_query(F.data == "main_menu:settings")
async def show_settings_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Open the settings menu from the main menu.

    Args:
        callback: Incoming callback query.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.set_state(SettingsFSM.menu)
    await callback.message.edit_text(
        "⚙️ Настройки\nВыберите параметр для изменения:",
        reply_markup=get_settings_menu_keyboard(),
    )


# =============================================================================
# Sub-menu navigations (set FSM state + show corresponding keyboard)
# =============================================================================


@router.callback_query(F.data == "settings:language")
async def choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the language selection keyboard.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    await state.set_state(SettingsFSM.language)
    await callback.message.edit_text(
        "🌐 Выберите язык:",
        reply_markup=get_language_keyboard(),
    )


@router.callback_query(F.data == "settings:timezone")
async def choose_timezone(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the timezone selection keyboard.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    await state.set_state(SettingsFSM.timezone)
    await callback.message.edit_text(
        "🕐 Выберите часовой пояс:",
        reply_markup=get_timezone_keyboard(),
    )


@router.callback_query(F.data == "settings:reminder_time")
async def choose_reminder_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the reminder time selection keyboard.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    await state.set_state(SettingsFSM.reminder_time)
    await callback.message.edit_text(
        "⏰ Выберите время ежедневного уведомления:",
        reply_markup=get_reminder_time_keyboard(),
    )


@router.callback_query(F.data == "settings:check_interval")
async def choose_check_interval(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the check interval selection keyboard.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    await state.set_state(SettingsFSM.check_interval)
    await callback.message.edit_text(
        "⏱ Выберите интервал проверки выполнения:",
        reply_markup=get_check_interval_keyboard(),
    )


# =============================================================================
# Setting value updates (save to DB + confirm)
# =============================================================================


@router.callback_query(F.data.startswith("settings:set_language:"))
async def set_language(callback: CallbackQuery) -> None:
    """Save the selected language and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_language:{code}``.
    """
    lang_code = callback.data.split(":", 2)[2]
    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
            )
            return
        user.language = lang_code
        await session.commit()

    await callback.message.edit_text(
        f"✅ Язык изменён на {lang_code.upper()}.",
        reply_markup=get_settings_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("settings:set_timezone:"))
async def set_timezone(callback: CallbackQuery) -> None:
    """Save the selected timezone and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_timezone:{offset}``.
    """
    tz_value = callback.data.split(":", 2)[2]
    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
            )
            return
        user.timezone = tz_value
        await session.commit()

    await callback.message.edit_text(
        f"✅ Часовой пояс изменён на UTC{tz_value}.",
        reply_markup=get_settings_menu_keyboard(),
    )


@router.callback_query(F.data == "reminder:off")
async def disable_reminder(callback: CallbackQuery) -> None:
    """Turn off the daily reminder.

    Args:
        callback: Incoming callback query.
    """
    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
            )
            return
        user.reminder_time = None
        await session.commit()

    await callback.message.edit_text(
        "🔕 Уведомления отключены.",
        reply_markup=get_settings_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("settings:set_reminder:"))
async def set_reminder_time(callback: CallbackQuery) -> None:
    """Save the selected reminder time and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_reminder:HH:MM``.
    """
    from datetime import time

    parts = callback.data.split(":")
    # data format: settings:set_reminder:HH:MM
    hour = int(parts[2])
    minute = int(parts[3])
    reminder = time(hour, minute)

    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
            )
            return
        user.reminder_time = reminder
        await session.commit()

    await callback.message.edit_text(
        f"⏰ Время уведомления установлено на {reminder.strftime('%H:%M')}.",
        reply_markup=get_settings_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("settings:set_interval:"))
async def set_check_interval(callback: CallbackQuery) -> None:
    """Save the selected check interval and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_interval:{minutes}``.
    """
    interval_str = callback.data.split(":", 2)[2]
    interval = int(interval_str)

    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
            )
            return
        user.check_interval = interval
        await session.commit()

    await callback.message.edit_text(
        f"⏱ Интервал проверки установлен на {interval} мин.",
        reply_markup=get_settings_menu_keyboard(),
    )


# =============================================================================
# Navigation
# =============================================================================


@router.callback_query(F.data == "settings:back")
async def back_to_settings_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the settings menu from any sub-menu.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    await state.set_state(SettingsFSM.menu)
    await callback.message.edit_text(
        "⚙️ Настройки\nВыберите параметр для изменения:",
        reply_markup=get_settings_menu_keyboard(),
    )


@router.callback_query(F.data == "nav:back")
async def settings_nav_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate back from the settings menu to the main menu.

    This handler is only reached when the user is in the settings menu.
    Higher-priority handlers in other routers handle other contexts.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )


@router.callback_query(F.data == "nav:cancel")
async def settings_nav_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate to the main menu, clearing the FSM state.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )
