"""Common handlers: /start command and main menu navigation."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db
from src.keyboards.inline import (
    MAIN_MENU_BUTTONS,
    get_main_menu_keyboard,
    get_new_habit_choice_keyboard,
)
from src.states.fsm import MainFSM

logger = logging.getLogger(__name__)

router = Router()
"""Router for common handlers (start, main menu)."""


def _get_button_label(callback_data: str) -> str:
    """Look up the human-readable label for a main menu callback_data value.

    Args:
        callback_data: The callback_data string (e.g. ``main_menu:habits``).

    Returns:
        The corresponding button label, or the raw callback_data if not found.
    """
    for label, data in MAIN_MENU_BUTTONS:
        if data == callback_data:
            return label
    return callback_data


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle the /start command.

    Creates a new user record if the user does not exist, otherwise updates
    ``updated_at``.  Sets the FSM state to ``MainFSM.main_menu`` and sends
    the main menu inline keyboard.

    Args:
        message: Incoming message object from Telegram.
        state: FSM context for the current user.
    """
    telegram_id = message.from_user.id

    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
            session.add(user)
            await session.commit()
            logger.info("Created new user with telegram_id=%d", telegram_id)
        else:
            # Touch updated_at via the model's onupdate hook
            user.updated_at = user.updated_at  # triggers onupdate
            await session.commit()
            logger.info("Updated existing user with telegram_id=%d", telegram_id)

    await state.set_state(MainFSM.main_menu)

    await message.answer(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )


# ===========================================================================
# Reply keyboard "🏠 Меню" handler — triggers /start flow
# ===========================================================================


@router.message(F.text == "🏠 Меню")
async def menu_reply_keyboard(message: Message, state: FSMContext) -> None:
    """Handle the persistent reply keyboard 'Меню' button."""
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await message.answer(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
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

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="nav:cancel")
    keyboard = builder.as_markup()

    help_text = (
        "📖 *Как пользоваться ботом:*\n\n"
        "• *➕ Создать привычку* — создайте новую привычку вручную "
        "или с помощью ИИ-ассистента\n"
        "• *📋 Привычки* — просмотр и управление вашими привычками\n"
        "• *📊 Статистика* — просмотр статистики выполнения привычек\n"
        "• *⚙️ Настройки* — настройка языка, часового пояса, напоминаний\n"
        "• *❓ Помощь* — вы здесь!\n\n"
        "По вопросам: @support"
    )
    await callback.message.edit_text(
        help_text,
        reply_markup=keyboard,
        parse_mode="Markdown",
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
    await callback.message.edit_text(
        "Выберите способ создания привычки:",
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

    label = _get_button_label(callback.data)
    await callback.message.edit_text(
        f"Функция '{label}' находится в разработке. Следите за обновлениями!",
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
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )


# ===========================================================================
# Input cancel buttons — used in text-input states
# ===========================================================================


@router.callback_query(F.data == "input:cancel")
async def handle_input_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the current text-input flow and return to the main menu."""
    await callback.answer()
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        "❌ Действие отменено.",
        reply_markup=get_main_menu_keyboard(),
    )


@router.callback_query(F.data == "input:goto_main")
async def handle_input_goto_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Silently exit the text-input flow and go to the main menu."""
    await callback.answer()
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )
