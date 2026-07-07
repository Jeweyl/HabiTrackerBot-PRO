"""Inline keyboard generators for the Telegram bot."""

from datetime import time

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


# ---------------------------------------------------------------------------
# Time selection keyboard — used in the New Habit wizard
# ---------------------------------------------------------------------------


def get_time_selection_keyboard(
    min_time: time | None = None,
    show_null_option: bool = False,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting a time of day.

    Displays hours 00:00–23:00 in a 3‑column grid.  If *min_time* is
    provided, only times strictly after *min_time* are shown.  The grid is
    always filled to full rows (3 columns) by adding dummy non‑clickable
    buttons.  If no time buttons remain after filtering, a single message
    button "Нет доступных вариантов" is shown instead of the time grid.

    When *show_null_option* is ``True``, the special button
    ``⏳ Без времени`` (callback ``time:null``) is included.  Navigation
    buttons ``⬅️ Назад`` / ``❌ Отмена`` appear on the last row.

    Args:
        min_time: If set, hide all time buttons whose value is less than
            or equal to *min_time*.  The ``time:null`` button is not affected.
        show_null_option: Whether to include the ``⏳ Без времени`` button
            (used for end-time selection, not for start-time).

    Returns:
        InlineKeyboardMarkup with the described layout.
    """
    builder = InlineKeyboardBuilder()

    # 1. Collect real time buttons (respecting the filter)
    real_count = 0
    for h in range(24):
        t = time(h, 0)
        if min_time is not None and t <= min_time:
            continue
        label = f"{h:02d}:00"
        builder.button(text=label, callback_data=f"time:{label}")
        real_count += 1

    # 2. If no real time buttons — show a placeholder message
    if real_count == 0:
        builder.button(
            text="Нет доступных вариантов",
            callback_data="ignore",
        )
        # Navigation row — two buttons always, plus null if requested
        nav_count = 2
        if show_null_option:
            builder.button(text="⏳ Без времени", callback_data="time:null")
            nav_count = 3
        builder.button(text="⬅️ Назад", callback_data="nav:back")
        builder.button(text="❌ Отмена", callback_data="nav:cancel")
        builder.adjust(1, nav_count - 1, 2)  # message, null/nav, nav
        return builder.as_markup()

    # 3. Fill to a multiple of 3 with dummy buttons
    remainder = real_count % 3
    if remainder != 0:
        for _ in range(3 - remainder):
            builder.button(text=" ", callback_data="ignore")

    # 4. Special buttons: "Без времени" (optional) + navigation
    if show_null_option:
        builder.button(text="⏳ Без времени", callback_data="time:null")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")

    # 5. Calculate rows: padded time grid is always a multiple of 3
    total_time = real_count + (3 - remainder if remainder else 0)
    rows = [3] * (total_time // 3)
    if show_null_option:
        rows.append(1)  # "Без времени"
    rows.append(2)  # back + cancel
    builder.adjust(*rows)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Frequency selection keyboard — used in the New Habit wizard
# ---------------------------------------------------------------------------

FREQUENCY_OPTIONS: list[tuple[str, str]] = [
    ("📅 Ежедневно", "freq:daily"),
    ("📆 По будням", "freq:weekdays"),
    ("🎉 По выходным", "freq:weekends"),
]
"""List of (label, callback_data) tuples for frequency selection."""


def get_frequency_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting habit frequency.

    Displays three frequency options plus a navigation row with
    ``⬅️ Назад`` and ``❌ Отмена``.

    Returns:
        InlineKeyboardMarkup with frequency buttons and navigation controls.
    """
    builder = InlineKeyboardBuilder()
    for label, callback_data in FREQUENCY_OPTIONS:
        builder.button(text=label, callback_data=callback_data)
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 2)  # 3 frequency rows + 1 nav row
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Edit field selection keyboard — used in the Habit editing flow
# ---------------------------------------------------------------------------


def get_edit_field_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting which habit field to edit.

    Returns:
        InlineKeyboardMarkup with 4 field buttons + cancel, one per row.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название", callback_data="edit_field:title")
    builder.button(text="🕐 Время начала", callback_data="edit_field:start_time")
    builder.button(text="🕐 Время окончания", callback_data="edit_field:end_time")
    builder.button(text="📅 Частота", callback_data="edit_field:frequency")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Delete confirmation keyboard — used in the Habit deletion flow
# ---------------------------------------------------------------------------


def get_delete_confirmation_keyboard(
    habit_id: int,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for confirming habit deletion.

    Args:
        habit_id: ID of the habit to be deleted.

    Returns:
        InlineKeyboardMarkup with confirm / cancel buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Подтвердить",
        callback_data=f"habit:confirm_delete:{habit_id}",
    )
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(2)
    return builder.as_markup()
