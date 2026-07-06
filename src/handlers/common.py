"""Common handlers: /start command and main menu navigation."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db
from src.keyboards.inline import MAIN_MENU_BUTTONS, get_main_menu_keyboard
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
    await callback.message.answer(
        f"Функция '{label}' находится в разработке. Следите за обновлениями!",
    )

    # Ensure the state remains on the main menu
    await state.set_state(MainFSM.main_menu)
