"""Settings menu handlers for the Telegram bot."""

from __future__ import annotations

import logging
from datetime import time

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db
from src.i18n import normalize_lang, t
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

_SUPPORTED_LANGUAGES = frozenset({"ru", "en"})

_SETTINGS_STATES = (
    SettingsFSM.menu,
    SettingsFSM.language,
    SettingsFSM.timezone,
    SettingsFSM.reminder_time,
    SettingsFSM.check_interval,
)


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


def _format_timezone_display(tz_value: str | None) -> str:
    """Human-readable timezone label for settings display."""
    raw = (tz_value or "UTC").strip()
    if not raw or raw.upper() == "UTC":
        return "UTC"
    if raw.startswith(("+", "-")):
        return f"UTC{raw}"
    if raw.upper().startswith("UTC"):
        return raw.upper() if raw[3:] == "" else f"UTC{raw[3:]}"
    return raw


def _format_reminder_display(reminder: time | None, lang: str) -> str:
    """Human-readable reminder time or «off»."""
    if reminder is None:
        return t("common.off", lang)
    return reminder.strftime("%H:%M")


def build_settings_menu_text(
    *,
    language: str = "ru",
    timezone: str = "UTC",
    reminder_time: time | None = None,
    check_interval: int | None = 15,
    notice: str | None = None,
) -> str:
    """Build settings menu text showing current values.

    Args:
        language: Stored user language code.
        timezone: Stored user timezone string.
        reminder_time: Preferred daily reminder time or None.
        check_interval: Check-in interval in minutes.
        notice: Optional one-line confirmation prepended above the menu.

    Returns:
        HTML-formatted settings menu body.
    """
    lang = normalize_lang(language)
    interval = check_interval if check_interval is not None else 15
    body = t(
        "settings.menu",
        lang,
        language=lang.upper(),
        timezone=_format_timezone_display(timezone),
        reminder=_format_reminder_display(reminder_time, lang),
        interval=t("common.minutes", lang, n=interval),
    )
    if notice:
        return f"{notice}\n\n{body}"
    return body


async def _load_user_lang(telegram_id: int) -> tuple[User | None, str]:
    """Load user and return ``(user_or_none, lang)`` (detached-safe fields)."""
    async with get_db() as session:
        user = await _get_user(session, telegram_id)
        if user is None:
            return None, "ru"
        # Touch attributes while session is open.
        lang = normalize_lang(user.language)
        return user, lang


async def _render_settings_for_telegram_id(
    telegram_id: int,
    *,
    notice: str | None = None,
    lang_override: str | None = None,
) -> tuple[str, InlineKeyboardMarkup, str]:
    """Load user settings and build menu text + keyboard.

    Returns:
        ``(text, keyboard, lang)``. If user is missing, returns a not-found
        message with an empty-ish main-menu keyboard fallback lang ``ru``.
    """
    async with get_db() as session:
        user = await _get_user(session, telegram_id)
        if user is None:
            lang = lang_override or "ru"
            return (
                t("common.user_not_found", lang),
                get_main_menu_keyboard(lang),
                lang,
            )
        lang = normalize_lang(lang_override or user.language)
        text = build_settings_menu_text(
            language=lang,
            timezone=user.timezone,
            reminder_time=user.reminder_time,
            check_interval=user.check_interval,
            notice=notice,
        )
        return text, get_settings_menu_keyboard(lang), lang


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
    text, keyboard, _lang = await _render_settings_for_telegram_id(
        callback.from_user.id,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


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
    _user, lang = await _load_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t("settings.choose_language", lang),
        reply_markup=get_language_keyboard(lang),
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
    _user, lang = await _load_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t("settings.choose_timezone", lang),
        reply_markup=get_timezone_keyboard(lang),
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
    _user, lang = await _load_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t("settings.choose_reminder", lang),
        reply_markup=get_reminder_time_keyboard(lang),
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
    _user, lang = await _load_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t("settings.choose_interval", lang),
        reply_markup=get_check_interval_keyboard(lang),
    )


# =============================================================================
# Setting value updates (save to DB + return to live settings menu)
# =============================================================================


@router.callback_query(F.data.startswith("settings:set_language:"))
async def set_language(callback: CallbackQuery, state: FSMContext) -> None:
    """Save the selected language and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_language:{code}``.
        state: FSM context.
    """
    lang_code = callback.data.split(":", 2)[2].strip().lower()
    await callback.answer()

    if lang_code not in _SUPPORTED_LANGUAGES:
        # Ignore unsupported codes without crashing; re-render current menu.
        await state.set_state(SettingsFSM.menu)
        text, keyboard, _ = await _render_settings_for_telegram_id(
            callback.from_user.id,
        )
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(t("common.user_not_found", lang_code))
            return
        user.language = lang_code
        await session.commit()

    await state.set_state(SettingsFSM.menu)
    notice = t("settings.lang_changed", lang_code, code=lang_code.upper())
    text, keyboard, _ = await _render_settings_for_telegram_id(
        callback.from_user.id,
        notice=notice,
        lang_override=lang_code,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("settings:set_timezone:"))
async def set_timezone(callback: CallbackQuery, state: FSMContext) -> None:
    """Save the selected timezone and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_timezone:{offset}``.
        state: FSM context.
    """
    tz_value = callback.data.split(":", 2)[2]
    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(t("common.user_not_found", "ru"))
            return
        user.timezone = tz_value
        lang = normalize_lang(user.language)
        await session.commit()

    await state.set_state(SettingsFSM.menu)
    notice = t("settings.tz_changed", lang, tz=tz_value)
    text, keyboard, _ = await _render_settings_for_telegram_id(
        callback.from_user.id,
        notice=notice,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "reminder:off")
async def disable_reminder(callback: CallbackQuery, state: FSMContext) -> None:
    """Turn off the daily reminder.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(t("common.user_not_found", "ru"))
            return
        user.reminder_time = None
        lang = normalize_lang(user.language)
        await session.commit()

    await state.set_state(SettingsFSM.menu)
    notice = t("settings.reminder_off", lang)
    text, keyboard, _ = await _render_settings_for_telegram_id(
        callback.from_user.id,
        notice=notice,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("settings:set_reminder:"))
async def set_reminder_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Save the selected reminder time and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_reminder:HH:MM``.
        state: FSM context.
    """
    parts = callback.data.split(":")
    # data format: settings:set_reminder:HH:MM
    hour = int(parts[2])
    minute = int(parts[3])
    reminder = time(hour, minute)

    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(t("common.user_not_found", "ru"))
            return
        user.reminder_time = reminder
        lang = normalize_lang(user.language)
        await session.commit()

    await state.set_state(SettingsFSM.menu)
    notice = t(
        "settings.reminder_set",
        lang,
        time=reminder.strftime("%H:%M"),
    )
    text, keyboard, _ = await _render_settings_for_telegram_id(
        callback.from_user.id,
        notice=notice,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("settings:set_interval:"))
async def set_check_interval(callback: CallbackQuery, state: FSMContext) -> None:
    """Save the selected check interval and return to the settings menu.

    Args:
        callback: Incoming callback query with data
            ``settings:set_interval:{minutes}``.
        state: FSM context.
    """
    interval_str = callback.data.split(":", 2)[2]
    interval = int(interval_str)

    await callback.answer()

    async with get_db() as session:
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.message.edit_text(t("common.user_not_found", "ru"))
            return
        user.check_interval = interval
        lang = normalize_lang(user.language)
        await session.commit()

    await state.set_state(SettingsFSM.menu)
    notice = t("settings.interval_set", lang, n=interval)
    text, keyboard, _ = await _render_settings_for_telegram_id(
        callback.from_user.id,
        notice=notice,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


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
    text, keyboard, _ = await _render_settings_for_telegram_id(
        callback.from_user.id,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "nav:back", StateFilter(*_SETTINGS_STATES))
async def settings_nav_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate back from the settings menu to the main menu.

    Scoped with ``StateFilter(SettingsFSM.*)`` to avoid router wars with
    habits / tasks / AI handlers that also listen for ``nav:back``.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    _user, lang = await _load_user_lang(callback.from_user.id)
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        t("main.menu", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


@router.callback_query(F.data == "nav:cancel", StateFilter(*_SETTINGS_STATES))
async def settings_nav_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate to the main menu, clearing the FSM state.

    Args:
        callback: Incoming callback query.
        state: FSM context.
    """
    await callback.answer()
    _user, lang = await _load_user_lang(callback.from_user.id)
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        t("main.menu", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )
