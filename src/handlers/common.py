"""Common handlers: /start command and main menu navigation."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from src.config import settings
from src.db.models import User
from src.db.session import get_db
from src.i18n import normalize_lang, t
from src.keyboards.inline import (
    get_main_menu_buttons,
    get_main_menu_keyboard,
    get_new_habit_choice_keyboard,
)
from src.states.fsm import MainFSM

logger = logging.getLogger(__name__)

router = Router()
"""Router for common handlers (start, main menu)."""


def _build_start_text(
    bot_public_url: str = "",
    channel_url: str = "",
    original_bot_username: str = "",
    lang: str = "ru",
) -> str:
    """Build the selling /start onboarding message (HTML).

    Link lines are included only when the corresponding value is non-empty.
    Empty URLs never produce a broken links block.

    Args:
        bot_public_url: Public t.me URL of this bot.
        channel_url: Public channel URL.
        original_bot_username: Original bot username without ``@``.
        lang: User language code.

    Returns:
        HTML-formatted onboarding text ending with a CTA to the main menu.
    """
    code = normalize_lang(lang)
    parts: list[str] = [
        t("start.title", code),
        "",
        t("start.body", code),
        "",
        t("start.how_to_title", code),
        t("start.how_to_1", code),
        t("start.how_to_2", code),
        t("start.how_to_3", code),
    ]

    link_lines: list[str] = []
    username = (original_bot_username or "").strip().lstrip("@")
    if username:
        link_lines.append(t("start.link_original", code, username=username))
    channel = (channel_url or "").strip()
    if channel:
        link_lines.append(t("start.link_channel", code, url=channel))
    bot_url = (bot_public_url or "").strip()
    if bot_url:
        link_lines.append(t("start.link_bot", code, url=bot_url))

    if link_lines:
        parts.extend(["", t("start.links_title", code), *link_lines])

    parts.extend(["", t("start.cta", code)])
    return "\n".join(parts)


def _get_button_label(callback_data: str, lang: str = "ru") -> str:
    """Look up the human-readable label for a main menu callback_data value.

    Args:
        callback_data: The callback_data string (e.g. ``main_menu:habits``).
        lang: User language code.

    Returns:
        The corresponding button label, or the raw callback_data if not found.
    """
    for label, data in get_main_menu_buttons(lang):
        if data == callback_data:
            return label
    return callback_data


async def _get_user_language(telegram_id: int) -> str:
    """Return stored language for *telegram_id*, defaulting to ``ru``."""
    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            return "ru"
        return normalize_lang(user.language)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle the /start command.

    Creates a new user record if the user does not exist, otherwise updates
    ``updated_at``.  Sets the FSM state to ``MainFSM.main_menu`` and sends
    the onboarding text with the main menu inline keyboard.

    Args:
        message: Incoming message object from Telegram.
        state: FSM context for the current user.
    """
    telegram_id = message.from_user.id
    username = message.from_user.username
    lang = "ru"

    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                language="ru",
                timezone="UTC",
            )
            session.add(user)
            await session.commit()
            logger.info("Created new user with telegram_id=%d", telegram_id)
            lang = "ru"
        else:
            # Keep username in sync and touch updated_at
            user.username = username
            lang = normalize_lang(user.language)
            await session.commit()
            logger.info("Updated existing user with telegram_id=%d", telegram_id)

    await state.set_state(MainFSM.main_menu)

    await message.answer(
        _build_start_text(
            bot_public_url=settings.BOT_PUBLIC_URL,
            channel_url=settings.CHANNEL_URL,
            original_bot_username=settings.ORIGINAL_BOT_USERNAME,
            lang=lang,
        ),
        reply_markup=get_main_menu_keyboard(lang),
    )


# ===========================================================================
# Reply keyboard "🏠 Меню" handler — triggers /start flow
# ===========================================================================


@router.message(F.text == "🏠 Меню")
async def menu_reply_keyboard(message: Message, state: FSMContext) -> None:
    """Handle the persistent reply keyboard 'Меню' button."""
    lang = await _get_user_language(message.from_user.id)
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await message.answer(
        t("main.menu", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


# ===========================================================================
# Specific main menu handlers — must be registered BEFORE the generic
# ``main_menu:*`` handler below.
# ===========================================================================


@router.callback_query(F.data == "main_menu:help")
async def handle_main_menu_help(callback: CallbackQuery, state: FSMContext) -> None:
    """Show a help message with bot usage instructions.

    Args:
        callback: Incoming callback query from the help button.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.set_state(MainFSM.main_menu)
    lang = await _get_user_language(callback.from_user.id)

    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.back", lang), callback_data="nav:cancel")
    keyboard = builder.as_markup()

    await callback.message.edit_text(
        t("help.text", lang),
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "main_menu:new_habit")
async def handle_main_menu_new_habit(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Show the new habit choice menu (manual or AI assistant).

    Args:
        callback: Incoming callback query from the new habit button.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.set_state(MainFSM.main_menu)
    lang = await _get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        t("main.new_habit_choice", lang),
        reply_markup=get_new_habit_choice_keyboard(),
    )


@router.callback_query(F.data.startswith("main_menu:"))
async def handle_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle taps on main menu inline buttons.

    Sends a placeholder message indicating the feature is under development
    and keeps the FSM state at ``MainFSM.main_menu``.

    Args:
        callback: Incoming callback query from Telegram.
        state: FSM context for the current user.
    """
    await callback.answer()
    lang = await _get_user_language(callback.from_user.id)

    label = _get_button_label(callback.data, lang)
    await callback.message.edit_text(
        t("main.under_development", lang, label=label),
    )

    # Ensure the state remains on the main menu
    await state.set_state(MainFSM.main_menu)


# ===========================================================================
# Fallback nav:cancel — catches all contexts not handled by tasks/habits
# ===========================================================================


@router.callback_query(F.data == "nav:cancel")
async def handle_cancel_fallback(callback: CallbackQuery, state: FSMContext) -> None:
    """Silently return to the main menu from non-habit/non-task contexts.

    This handler has the lowest priority (common router is included last)
    and only fires when the user presses ``nav:cancel`` from screens like
    the habit list, schedule view, or main menu itself.
    """
    await callback.answer()
    lang = await _get_user_language(callback.from_user.id)
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        t("main.menu", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


# ===========================================================================
# Input cancel buttons — used in text-input states
# ===========================================================================


@router.callback_query(F.data == "input:cancel")
async def handle_input_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the current text-input flow and return to the main menu."""
    await callback.answer()
    lang = await _get_user_language(callback.from_user.id)
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        t("common.cancelled", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


@router.callback_query(F.data == "input:goto_main")
async def handle_input_goto_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Silently exit the text-input flow and go to the main menu."""
    await callback.answer()
    lang = await _get_user_language(callback.from_user.id)
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        t("main.menu", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )
