"""Reply (persistent) keyboard generators for the Telegram bot."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def get_main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    """Build a persistent reply keyboard with a single 'Меню' button.

    Returns:
        ReplyKeyboardMarkup with one button that triggers the main menu.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Меню")]],
        resize_keyboard=True,
    )