"""Inline keyboard generators for the Telegram bot."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAIN_MENU_BUTTONS: list[tuple[str, str]] = [
    ("📋 Мои привычки", "main_menu:habits"),
    ("➕ Новая привычка", "main_menu:new_habit"),
    ("✅ Новая задача", "main_menu:new_task"),
    ("Посмотреть список дел на сегодня", "main_menu:today_tasks"),
    ("Отметить выполненные задачи за сегодня", "main_menu:complete_tasks"),
    ("📊 Статистика", "main_menu:statistics"),
    ("⚙️ Настройки", "main_menu:settings"),
    ("❓ Помощь", "main_menu:help"),
]
"""List of (label, callback_data) tuples for the main menu buttons."""


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the main menu inline keyboard with one button per row.

    Returns:
        InlineKeyboardMarkup with 8 buttons, each on its own row.
    """
    builder = InlineKeyboardBuilder()
    for label, callback_data in MAIN_MENU_BUTTONS:
        builder.button(text=label, callback_data=callback_data)
    builder.adjust(1)  # One button per row
    return builder.as_markup()
