"""Inline keyboard generators for the Telegram bot."""

import calendar
from datetime import date, time

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAIN_MENU_BUTTONS: list[tuple[str, str]] = [
    ("📋 Мои привычки", "main_menu:habits"),
    ("➕ Новая привычка", "main_menu:new_habit"),
    ("➕ Новая задача", "main_menu:new_task"),
    ("📅 Расписание на сегодня", "main_menu:today_tasks"),
    ("📅 Расписание", "main_menu:view_schedule"),
    ("✅ Отметить выполненные дела", "main_menu:complete_tasks"),
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


# ---------------------------------------------------------------------------
# Month calendar keyboard — used for date selection
# ---------------------------------------------------------------------------

WEEKDAY_HEADERS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
"""Column headers for the calendar grid."""

MONTH_NAMES = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
"""Russian month names indexed by month number (1‑based)."""


def get_month_calendar_keyboard(
    year: int,
    month: int,
) -> InlineKeyboardMarkup:
    """Build a month calendar grid with navigation controls.

    The calendar renders a 7‑column grid (Mon–Sun) for the given *year*
    and *month*.  Each day is a button with callback
    ``calendar:day:YYYY-MM-DD``.  The current month/year is shown in the
    first row as a non‑clickable label.  Navigation buttons allow
    switching to the previous or next month and going back to the main
    menu.

    Args:
        year: Year to display (e.g. 2026).
        month: Month to display (1‑based, 1 = January).

    Returns:
        InlineKeyboardMarkup with the calendar grid and controls.
    """
    builder = InlineKeyboardBuilder()

    # --- Row 1: month/year header (non‑clickable) ---
    month_label = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
    builder.button(text=f"{month_label} {year}", callback_data="ignore")

    # --- Row 2: weekday headers ---
    for header in WEEKDAY_HEADERS:
        builder.button(text=header, callback_data="ignore")

    # --- Rows 3+: day grid ---
    # calendar.monthcalendar returns weeks as lists of 7 ints; 0 = not in month
    weeks = calendar.monthcalendar(year, month)
    today = date.today()
    for week in weeks:
        for day_num in week:
            if day_num == 0:
                # Empty cell
                builder.button(text=" ", callback_data="ignore")
            else:
                cell_date = date(year, month, day_num)
                label = str(day_num)
                # Highlight today
                if cell_date == today:
                    label = f"•{day_num}•"
                builder.button(
                    text=label,
                    callback_data=f"calendar:day:{cell_date.isoformat()}",
                )

    # --- Navigation row ---
    # Previous month
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    builder.button(
        text="⬅️ Предыдущий",
        callback_data=f"calendar:month:{prev_year}:{prev_month}",
    )
    # Next month
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    builder.button(
        text="➡️ Следующий",
        callback_data=f"calendar:month:{next_year}:{next_month}",
    )
    # Back to main menu
    builder.button(text="🔙 Назад", callback_data="nav:back")

    # Adjust: 1 (header) + 7 (weekdays) + N*7 (days) + 3 (nav)
    num_weeks = len(weeks)
    builder.adjust(1, 7, *([7] * num_weeks), 3)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Day actions keyboard — shown after selecting a day
# ---------------------------------------------------------------------------


def get_day_keyboard(selected_date: date) -> InlineKeyboardMarkup:
    """Build an inline keyboard with actions for a selected day.

    Provides buttons to add a task and navigate back to the month calendar.

    Args:
        selected_date: The date selected by the user.

    Returns:
        InlineKeyboardMarkup with add / back / main menu buttons.
    """
    iso = selected_date.isoformat()
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Добавить задачу", callback_data=f"task:add:{iso}")
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.button(text="🏠 В главное меню", callback_data="nav:cancel")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Task confirmation keyboard — used before saving a new task
# ---------------------------------------------------------------------------


def get_task_confirm_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for confirming task creation.

    Returns:
        InlineKeyboardMarkup with ``✅ Подтвердить``, ``⬅️ Назад``,
        and ``❌ Отмена`` buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="task:save")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Task completion keyboard — one button per task with status icon
# ---------------------------------------------------------------------------


def get_tasks_completion_keyboard(
    tasks: list,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard where each task is a toggle button.

    The button text includes a status icon (✅ / ⬜), the task title,
    and the time range.  Tapping the button fires ``task:toggle:{id}``.

    Args:
        tasks: A list of ``Task`` ORM objects (must have ``id``,
            ``title``, ``start_time``, ``end_time``, ``is_completed``).

    Returns:
        InlineKeyboardMarkup with one task button per row, plus a
        ``🔙 Назад`` button on the last row.
    """
    builder = InlineKeyboardBuilder()
    for task in tasks:
        status = "✅" if task.is_completed else "⬜"
        if task.end_time is None:
            time_str = f"{task.start_time.strftime('%H:%M')}, без окончания"
        else:
            time_str = (
                f"{task.start_time.strftime('%H:%M')}"
                f"–{task.end_time.strftime('%H:%M')}"
            )
        label = f"{status} {task.title} ({time_str})"
        builder.button(text=label, callback_data=f"task:toggle:{task.id}")
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.adjust(1)  # one button per row
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Schedule management keyboard — task list with manage buttons
# ---------------------------------------------------------------------------


def get_schedule_management_keyboard(
    tasks: list,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with each task as a clickable manage button.

    Args:
        tasks: A list of ``Task`` ORM objects.

    Returns:
        InlineKeyboardMarkup with one task-per-row and 🔙 Назад button.
    """
    builder = InlineKeyboardBuilder()
    for task in tasks:
        status = "✅" if task.is_completed else "⬜"
        if task.end_time is None:
            time_str = f"{task.start_time.strftime('%H:%M')}, без окончания"
        else:
            time_str = (
                f"{task.start_time.strftime('%H:%M')}"
                f"–{task.end_time.strftime('%H:%M')}"
            )
        label = f"{status} {task.title} ({time_str})"
        builder.button(text=label, callback_data=f"task:manage:{task.id}")
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Simple schedule keyboard — navigation only (no task management buttons)
# ---------------------------------------------------------------------------


def get_simple_schedule_keyboard() -> InlineKeyboardMarkup:
    """Build a minimal keyboard with only navigation buttons.

    Used when showing the schedule in read-only mode (e.g. before adding
    a task).

    Returns:
        InlineKeyboardMarkup with 🔙 Назад and 🏠 В главное меню buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.button(text="🏠 В главное меню", callback_data="nav:cancel")
    builder.adjust(2)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Conflict resolution keyboard — force / edit / cancel
# ---------------------------------------------------------------------------


def get_conflict_resolution_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for resolving time conflicts.

    Returns:
        InlineKeyboardMarkup with 4 action buttons + navigation.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="💪 Всё равно добавить",
        callback_data="conflict:force_add",
    )
    builder.button(
        text="📋 Изменить расписание",
        callback_data="conflict:edit_schedule",
    )
    builder.button(
        text="✏️ Изменить задачу",
        callback_data="conflict:edit_task",
    )
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 2)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Task delete confirmation keyboard
# ---------------------------------------------------------------------------


def get_task_delete_confirmation_keyboard(
    task_id: int,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for confirming task deletion.

    Args:
        task_id: ID of the task to be deleted.

    Returns:
        InlineKeyboardMarkup with confirm / cancel buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Подтвердить",
        callback_data=f"task:confirm_delete:{task_id}",
    )
    builder.button(text="❌ Отмена", callback_data="nav:back")
    builder.adjust(2)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Task management keyboard — shown when a task is selected from the schedule
# ---------------------------------------------------------------------------


def get_task_management_keyboard(
    task_id: int,
    has_habit: bool = False,
    is_modified: bool = False,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with task management actions.

    Args:
        task_id: ID of the task to manage.
        has_habit: Whether the task is linked to a habit.
        is_modified: Whether the task differs from its habit template.

    Returns:
        InlineKeyboardMarkup with delete / edit / reset / back / cancel buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Удалить",
        callback_data=f"task:delete:{task_id}",
    )
    builder.button(
        text="✏️ Редактировать",
        callback_data=f"task:edit:{task_id}",
    )
    if has_habit and is_modified:
        builder.button(
            text="🔄 Сбросить к привычке",
            callback_data=f"task:reset:{task_id}",
        )
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    row_spec = [1, 1]
    if has_habit and is_modified:
        row_spec.append(1)
    row_spec.append(2)
    builder.adjust(*row_spec)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Edit task field selection keyboard
# ---------------------------------------------------------------------------


def get_edit_task_field_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting which task field to edit.

    Returns:
        InlineKeyboardMarkup with 4 field buttons + cancel.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название", callback_data="edit_task_field:title")
    builder.button(text="📅 Дата", callback_data="edit_task_field:date")
    builder.button(text="🕐 Время начала", callback_data="edit_task_field:start_time")
    builder.button(text="🕐 Время окончания", callback_data="edit_task_field:end_time")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Confirm task changes keyboard
# ---------------------------------------------------------------------------


def get_task_confirm_changes_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for confirming task edit changes.

    Returns:
        InlineKeyboardMarkup with confirm / cancel buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Подтвердить",
        callback_data="task:confirm_changes",
    )
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(2)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Cancel input keyboard — shown during text-input states
# ---------------------------------------------------------------------------


def get_cancel_input_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard with cancel/exit buttons for text-input states.

    Returns:
        InlineKeyboardMarkup with ❌ Отмена and 🏠 В главное меню buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="input:cancel")
    builder.button(text="🏠 В главное меню", callback_data="input:goto_main")
    builder.adjust(2)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# AI assistant keyboard — Yes / No / Skip / Back / Cancel
# ---------------------------------------------------------------------------


def get_ai_assistant_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for the AI assistant dialog flow.

    Provides action buttons for navigating the AI assistant wizard:
    ``✅ Да`` (assist:yes), ``❌ Нет`` (assist:no),
    ``⏭ Пропустить`` (assist:skip), ``⬅️ Назад`` (nav:back),
    ``❌ Отмена`` (nav:cancel).

    Returns:
        InlineKeyboardMarkup with two rows: Yes/No/Skip and Back/Cancel.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data="assist:yes")
    builder.button(text="❌ Нет", callback_data="assist:no")
    builder.button(text="⏭ Пропустить", callback_data="assist:skip")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(3, 2)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Habit conflict resolution keyboard
# ---------------------------------------------------------------------------


def get_habit_conflict_resolution_keyboard(
    is_edit: bool = False,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for resolving habit time conflicts.

    Args:
        is_edit: If ``True``, include the "Edit Conflicting Tasks" button.

    Returns:
        InlineKeyboardMarkup with conflict resolution buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⏰ Изменить время",
        callback_data="conflict_habit:change_time",
    )
    builder.button(
        text="📆 Изменить частоту",
        callback_data="conflict_habit:change_frequency",
    )
    builder.button(
        text="📅 Изменить расписание",
        callback_data="conflict_habit:edit_schedule",
    )
    if is_edit:
        builder.button(
            text="📋 Редактировать конфликтующие задачи",
            callback_data="conflict_habit:edit_tasks",
        )
    builder.button(
        text="✅ Всё равно добавить",
        callback_data="conflict_habit:force_add",
    )
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    row_spec = [1, 1, 1]
    if is_edit:
        row_spec.append(1)
    row_spec.extend([1, 1])
    builder.adjust(*row_spec)
    return builder.as_markup()
