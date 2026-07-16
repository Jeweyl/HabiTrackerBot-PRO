"""Inline keyboard generators for the Telegram bot."""

import calendar
from datetime import date, time

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.i18n import t
from src.utils.keyboard_width import finalize_markup

# callback_data values are stable; labels come from i18n.
# Order: habits first among callbacks; dashboard web_app is prepended separately.
_MAIN_MENU_CALLBACKS: list[tuple[str, str]] = [
    ("main.habits", "main_menu:habits"),
    ("main.new_habit", "main_menu:new_habit"),
    ("main.new_task", "main_menu:new_task"),
    ("main.today_tasks", "main_menu:today_tasks"),
    ("main.view_schedule", "main_menu:view_schedule"),
    ("main.complete_tasks", "main_menu:complete_tasks"),
    ("main.statistics", "main_menu:statistics"),
    ("main.settings", "main_menu:settings"),
    ("main.help", "main_menu:help"),
]


def get_main_menu_buttons(lang: str = "ru") -> list[tuple[str, str]]:
    """Return (label, callback_data) pairs for the main menu in *lang*."""
    return [(t(key, lang), cb) for key, cb in _MAIN_MENU_CALLBACKS]


# Backwards-compatible default (Russian) used by older tests/helpers.
MAIN_MENU_BUTTONS: list[tuple[str, str]] = get_main_menu_buttons("ru")
"""List of (label, callback_data) tuples for the main menu buttons (RU)."""


def get_main_menu_keyboard(
    lang: str = "ru",
    *,
    dashboard_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Build the main menu inline keyboard with one button per row.

    When *dashboard_url* is set, a Web App button is placed **first** (above
    «Habits»), opening the Vue dashboard inside Telegram.

    Args:
        lang: User language code (``ru`` / ``en``).
        dashboard_url: Optional one-time login URL for the web dashboard.

    Returns:
        InlineKeyboardMarkup with one button per row.
    """
    builder = InlineKeyboardBuilder()
    if dashboard_url:
        builder.row(
            InlineKeyboardButton(
                text=t("main.open_dashboard", lang),
                web_app=WebAppInfo(url=dashboard_url),
            )
        )
    for label, callback_data in get_main_menu_buttons(lang):
        builder.row(
            InlineKeyboardButton(text=label, callback_data=callback_data)
        )
    return finalize_markup(builder)




# ---------------------------------------------------------------------------
# Time selection keyboard — two-step: hour → minutes (00/15/30/45)
# ---------------------------------------------------------------------------


def get_time_selection_keyboard(
    min_time: time | None = None,
    show_null_option: bool = False,
) -> InlineKeyboardMarkup:
    """Build step-1 hour keyboard (alias for :func:`get_hour_selection_keyboard`).

    Args:
        min_time: If set, hide hours that have no 15-min slot strictly after
            *min_time*.  The ``time:null`` button is not affected.
        show_null_option: Whether to include the ``⏳ Без времени`` button
            (used for end-time selection, not for start-time).

    Returns:
        InlineKeyboardMarkup with hour buttons (``time:hour:HH``).
    """
    return get_hour_selection_keyboard(
        min_time=min_time,
        show_null_option=show_null_option,
    )


def get_hour_selection_keyboard(
    min_time: time | None = None,
    show_null_option: bool = False,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting an hour of day (step 1).

    Displays hours ``00``–``23`` in a 4-column grid.  If *min_time* is
    provided, only hours that still have at least one allowed 15-minute
    slot strictly after *min_time* are shown.  If no hours remain, a
    placeholder button is shown instead of the grid.

    Callbacks: ``time:hour:HH``.  Navigation: ``nav:back`` / ``nav:cancel``.
    Optional ``time:null`` when *show_null_option* is True.

    Args:
        min_time: Hide hours with no valid quarter-hour after this time.
        show_null_option: Include the open-ended end-time button.

    Returns:
        InlineKeyboardMarkup for hour selection.
    """
    from src.utils.time_picker import available_hours

    builder = InlineKeyboardBuilder()
    hours = available_hours(min_time)
    real_count = 0
    for h in hours:
        builder.button(text=f"{h:02d}", callback_data=f"time:hour:{h:02d}")
        real_count += 1

    if real_count == 0:
        builder.button(text="Нет доступных вариантов", callback_data="ignore")
        if show_null_option:
            builder.button(text="⏳ Без времени", callback_data="time:null")
        builder.button(text="⬅️ Назад", callback_data="nav:back")
        builder.button(text="❌ Отмена", callback_data="nav:cancel")
        if show_null_option:
            builder.adjust(1, 1, 2)
        else:
            builder.adjust(1, 2)
        return finalize_markup(builder)

    # Pad to a multiple of 4
    remainder = real_count % 4
    if remainder != 0:
        for _ in range(4 - remainder):
            builder.button(text=" ", callback_data="ignore")

    if show_null_option:
        builder.button(text="⏳ Без времени", callback_data="time:null")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")

    total_hours = real_count + (4 - remainder if remainder else 0)
    rows = [4] * (total_hours // 4)
    if show_null_option:
        rows.append(1)
    rows.append(2)
    builder.adjust(*rows)
    return finalize_markup(builder)


def get_minute_selection_keyboard(
    hour: int,
    min_time: time | None = None,
    show_null_option: bool = False,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting minutes (step 2).

    Shows quarter-hour options ``00 / 15 / 30 / 45`` for the given *hour*.
    Callbacks: ``time:HH:MM``.  Filtered by *min_time* (strictly after).

    Args:
        hour: Hour chosen in step 1 (0–23).
        min_time: Hide slots less than or equal to this time.
        show_null_option: Include the open-ended end-time button.

    Returns:
        InlineKeyboardMarkup for minute selection.
    """
    from src.utils.time_picker import available_minutes

    builder = InlineKeyboardBuilder()
    minutes = available_minutes(hour, min_time)
    real_count = 0
    for m in minutes:
        label = f"{m:02d}"
        builder.button(
            text=label,
            callback_data=f"time:{hour:02d}:{m:02d}",
        )
        real_count += 1

    if real_count == 0:
        builder.button(text="Нет доступных вариантов", callback_data="ignore")
        if show_null_option:
            builder.button(text="⏳ Без времени", callback_data="time:null")
        builder.button(text="⬅️ Назад", callback_data="nav:back")
        builder.button(text="❌ Отмена", callback_data="nav:cancel")
        if show_null_option:
            builder.adjust(1, 1, 2)
        else:
            builder.adjust(1, 2)
        return finalize_markup(builder)

    if show_null_option:
        builder.button(text="⏳ Без времени", callback_data="time:null")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")

    rows: list[int] = [real_count]
    if show_null_option:
        rows.append(1)
    rows.append(2)
    builder.adjust(*rows)
    return finalize_markup(builder)



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
    return finalize_markup(builder)


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
    return finalize_markup(builder)


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
    return finalize_markup(builder)


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
    return finalize_markup(builder)


# ---------------------------------------------------------------------------
# Day actions keyboard — shown after selecting a day
# ---------------------------------------------------------------------------


def get_day_keyboard(selected_date: date) -> InlineKeyboardMarkup:
    """Build an inline keyboard with actions for a selected day.

    Provides buttons to add a task (manual / AI) and navigate back.

    Args:
        selected_date: The date selected by the user.

    Returns:
        InlineKeyboardMarkup with add / AI / back / main menu buttons.
    """
    iso = selected_date.isoformat()
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Добавить задачу", callback_data=f"task:add:{iso}")
    builder.button(text="🤖 С AI", callback_data=f"task:ai:{iso}")
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.button(text="🏠 В главное меню", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 1)
    return finalize_markup(builder)


def get_new_task_choice_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Build keyboard for choosing manual vs AI-assisted task creation.

    Args:
        lang: User language code.

    Returns:
        InlineKeyboardMarkup with manual / AI / back buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("task_ai.btn_manual", lang),
        callback_data="new_task:manual",
    )
    builder.button(
        text=t("task_ai.btn_ai", lang),
        callback_data="new_task:ai",
    )
    builder.button(text=t("common.back", lang), callback_data="nav:back")
    builder.adjust(1, 1, 1)
    return finalize_markup(builder)


def get_ai_task_fallback_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Fallback keyboard when task AI is unavailable.

    Args:
        lang: User language code.

    Returns:
        InlineKeyboardMarkup with manual creation and back.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("task_ai.btn_manual_create", lang),
        callback_data="new_task:manual",
    )
    builder.button(text=t("common.back", lang), callback_data="nav:back")
    builder.adjust(1, 1)
    return finalize_markup(builder)


def get_ai_task_choice_keyboard(
    options: list[str],
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Choice keyboard for task AI clarifying questions (``assist_task:``).

    Args:
        options: Choice labels.
        lang: User language code.

    Returns:
        InlineKeyboardMarkup with option buttons + skip/nav.
    """
    builder = InlineKeyboardBuilder()
    for i, label in enumerate(options):
        text = (label or "").strip() or f"Option {i + 1}"
        builder.button(text=text[:64], callback_data=f"assist_task:choice:{i}")
    builder.button(text=t("task_ai.skip", lang), callback_data="assist_task:skip")
    builder.button(text=t("common.back", lang), callback_data="nav:back")
    builder.button(text=t("common.cancel", lang), callback_data="nav:cancel")
    rows = [1] * len(options) + [1, 2]
    builder.adjust(*rows)
    return finalize_markup(builder)


def get_ai_task_plan_confirm_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Yes/No keyboard for AI task plan preview (``assist_task:``).

    Args:
        lang: User language code.

    Returns:
        InlineKeyboardMarkup with confirm / decline / cancel.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=t("task_ai.yes", lang), callback_data="assist_task:yes")
    builder.button(text=t("task_ai.no", lang), callback_data="assist_task:no")
    builder.button(text=t("common.cancel", lang), callback_data="nav:cancel")
    builder.adjust(2, 1)
    return finalize_markup(builder)



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
    return finalize_markup(builder)


# ---------------------------------------------------------------------------
# Task completion keyboard — one button per task with status icon
# ---------------------------------------------------------------------------


def _format_task_time_label(task, lang: str = "ru") -> str:
    """Human-readable time range for a task button/list row."""
    if getattr(task, "start_time", None) is None:
        return t("task.untimed", lang)
    if task.end_time is None:
        return f"{task.start_time.strftime('%H:%M')}, {t('task.open_ended', lang)}"
    return (
        f"{task.start_time.strftime('%H:%M')}"
        f"–{task.end_time.strftime('%H:%M')}"
    )


def get_tasks_completion_keyboard(
    tasks: list,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Build an inline keyboard where each task is a toggle button.

    The button text includes a status icon (✅ / ⬜), the task title,
    and the time range.  Tapping the button fires ``task:toggle:{id}``.

    Args:
        tasks: A list of ``Task`` ORM objects (must have ``id``,
            ``title``, ``start_time``, ``end_time``, ``is_completed``).
        lang: User language code for untimed / open-ended labels.

    Returns:
        InlineKeyboardMarkup with one task button per row, plus a
        ``🔙 Назад`` button on the last row.
    """
    builder = InlineKeyboardBuilder()
    for task in tasks:
        status = "✅" if task.is_completed else "⬜"
        time_str = _format_task_time_label(task, lang)
        label = f"{status} {task.title} ({time_str})"
        builder.button(text=label, callback_data=f"task:toggle:{task.id}")
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.adjust(1)  # one button per row
    return finalize_markup(builder)



# ---------------------------------------------------------------------------
# Schedule management keyboard — task list with manage buttons
# ---------------------------------------------------------------------------


def get_schedule_management_keyboard(
    tasks: list,
    *,
    add_date: date | None = None,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with each task as a clickable manage button.

    Args:
        tasks: A list of ``Task`` ORM objects.
        add_date: If set, show «Add task» for this date above Back.
        lang: User language code.

    Returns:
        InlineKeyboardMarkup with one task-per-row, optional add, and Back.
    """
    builder = InlineKeyboardBuilder()
    for task in tasks:
        status = "✅" if task.is_completed else "⬜"
        time_str = _format_task_time_label(task, lang)
        label = f"{status} {task.title} ({time_str})"
        builder.button(text=label, callback_data=f"task:manage:{task.id}")
    if add_date is not None:
        builder.button(
            text=t("task.add_today", lang),
            callback_data=f"task:add:{add_date.isoformat()}",
        )
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.adjust(1)
    return finalize_markup(builder)


def get_ask_rollover_keyboard(task_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Yes/No keyboard after creating a task (auto-rollover prompt)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("task.rollover_yes", lang),
        callback_data=f"task:rollover_yes:{task_id}",
    )
    builder.button(
        text=t("task.rollover_no", lang),
        callback_data=f"task:rollover_no:{task_id}",
    )
    builder.adjust(1, 1)
    return finalize_markup(builder)



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
    return finalize_markup(builder)


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
    return finalize_markup(builder)


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
    return finalize_markup(builder)


# ---------------------------------------------------------------------------
# Task management keyboard — shown when a task is selected from the schedule
# ---------------------------------------------------------------------------


def get_task_action_keyboard(
    task_id: int,
    is_completed: bool = False,
    has_habit: bool = False,
    is_modified: bool = False,
    auto_rollover: bool = False,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with task action buttons.

    Shown when the user taps a task in the schedule.  Includes a toggle
    button for completion status, edit, delete, auto-rollover, optional
    reset-to-habit, back, and main menu.

    Args:
        task_id: ID of the task.
        is_completed: Current completion status of the task.
        has_habit: Whether the task is linked to a habit.
        is_modified: Whether the task differs from its habit template.
        auto_rollover: Current auto-rollover flag for the task.
        lang: User language code.

    Returns:
        InlineKeyboardMarkup with action buttons.
    """
    builder = InlineKeyboardBuilder()
    if is_completed:
        builder.button(
            text="❌ Отметить невыполненным",
            callback_data=f"task:toggle:{task_id}",
        )
    else:
        builder.button(
            text="✅ Отметить выполненным",
            callback_data=f"task:toggle:{task_id}",
        )
    builder.button(
        text="✏️ Редактировать",
        callback_data=f"task:edit:{task_id}",
    )
    builder.button(
        text="🗑 Удалить",
        callback_data=f"task:delete:{task_id}",
    )
    rollover_key = (
        "task.btn_rollover_on" if auto_rollover else "task.btn_rollover_off"
    )
    builder.button(
        text=t(rollover_key, lang),
        callback_data=f"task:toggle_rollover:{task_id}",
    )
    if has_habit and is_modified:
        builder.button(
            text="🔄 Сбросить к привычке",
            callback_data=f"task:reset:{task_id}",
        )
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="🏠 В главное меню", callback_data="nav:cancel")
    row_spec = [1, 1, 1, 1]
    if has_habit and is_modified:
        row_spec.append(1)
    row_spec.append(2)
    builder.adjust(*row_spec)
    return finalize_markup(builder)



# ---------------------------------------------------------------------------
# Edit task field selection keyboard
# ---------------------------------------------------------------------------


def get_edit_task_field_keyboard(
    task_id: int | None = None,
    is_completed: bool = False,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting which task field to edit.

    When *task_id* is provided, a toggle-completion button is included
    so the user can flip the task status without leaving the edit screen.

    Args:
        task_id: ID of the task being edited (optional — if ``None``,
            the toggle button is omitted for backwards compatibility).
        is_completed: Current completion status of the task.

    Returns:
        InlineKeyboardMarkup with field buttons, optional toggle, and cancel.
    """
    builder = InlineKeyboardBuilder()
    if task_id is not None:
        if is_completed:
            builder.button(
                text="❌ Отметить невыполненным",
                callback_data=f"task:toggle:{task_id}",
            )
        else:
            builder.button(
                text="✅ Отметить выполненным",
                callback_data=f"task:toggle:{task_id}",
            )
    builder.button(text="📝 Название", callback_data="edit_task_field:title")
    builder.button(text="📅 Дата", callback_data="edit_task_field:date")
    builder.button(text="🕐 Время начала", callback_data="edit_task_field:start_time")
    builder.button(text="🕐 Время окончания", callback_data="edit_task_field:end_time")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    row_spec = []
    if task_id is not None:
        row_spec.append(1)  # toggle button row
    row_spec.extend([1, 1, 1, 1, 1])  # 4 fields + cancel
    builder.adjust(*row_spec)
    return finalize_markup(builder)


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
    return finalize_markup(builder)


# ---------------------------------------------------------------------------
# New habit choice keyboard — manual or AI assistant
# ---------------------------------------------------------------------------


def get_new_habit_choice_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for choosing between manual and AI-assisted
    habit creation.

    Returns:
        InlineKeyboardMarkup with two choice buttons and a back button.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✍️ Добавить вручную",
        callback_data="new_habit:manual",
    )
    builder.button(
        text="🤖 Запросить помощь ассистента",
        callback_data="new_habit:ai",
    )
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.adjust(1, 1, 1)
    return finalize_markup(builder)


# ---------------------------------------------------------------------------
# AI fallback keyboard — shown when the AI service is unavailable
# ---------------------------------------------------------------------------


def get_ai_fallback_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for the AI error fallback scenario.

    Offers a button to switch to manual creation and a back button.

    Returns:
        InlineKeyboardMarkup with manual creation and back buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✍️ Создать вручную",
        callback_data="new_habit:manual",
    )
    builder.button(text="🔙 Назад", callback_data="nav:back")
    builder.adjust(1, 1)
    return finalize_markup(builder)


def get_ai_choice_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    """Build an inline keyboard for AI clarifying choice questions.

    Args:
        options: Choice labels (indexed into ``assist:choice:{i}``).

    Returns:
        InlineKeyboardMarkup with one button per option plus skip/nav.
    """
    builder = InlineKeyboardBuilder()
    for i, label in enumerate(options):
        text = (label or "").strip() or f"Option {i + 1}"
        # Telegram callback_data limit 64 bytes; keep index-based payload.
        builder.button(text=text[:64], callback_data=f"assist:choice:{i}")
    builder.button(text="⏭ Пропустить", callback_data="assist:skip")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    # One option per row, then skip, then back+cancel
    rows = [1] * len(options) + [1, 2]
    builder.adjust(*rows)
    return finalize_markup(builder)


def get_ai_plan_confirm_keyboard() -> InlineKeyboardMarkup:
    """Build Yes/No keyboard for AI plan preview confirmation.

    Returns:
        InlineKeyboardMarkup with confirm / decline / cancel.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data="assist:yes")
    builder.button(text="❌ Нет", callback_data="assist:no")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(2, 1)
    return finalize_markup(builder)


# ---------------------------------------------------------------------------
# Adaptive question keyboards — used in the AI assistant wizard
# ---------------------------------------------------------------------------


def get_sport_intensity_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting sport intensity level.

    Returns:
        InlineKeyboardMarkup with intensity options, skip, and navigation.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🌱 Начинающий", callback_data="assist:intensity:beginner")
    builder.button(text="🏃 Средний", callback_data="assist:intensity:intermediate")
    builder.button(text="💪 Продвинутый", callback_data="assist:intensity:advanced")
    builder.button(text="⏭ Пропустить", callback_data="assist:skip")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 1, 2)
    return finalize_markup(builder)


def get_sport_duration_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting sport duration per day.

    Returns:
        InlineKeyboardMarkup with duration options, skip, and navigation.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="15 мин", callback_data="assist:duration:15")
    builder.button(text="30 мин", callback_data="assist:duration:30")
    builder.button(text="45 мин", callback_data="assist:duration:45")
    builder.button(text="60 мин", callback_data="assist:duration:60")
    builder.button(text="⏭ Пропустить", callback_data="assist:skip")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 1, 1, 2)
    return finalize_markup(builder)


def get_hygiene_time_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting time of day for hygiene habits.

    Returns:
        InlineKeyboardMarkup with time-of-day options, skip, and navigation.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🌅 Утром", callback_data="assist:time:morning")
    builder.button(text="🌙 Вечером", callback_data="assist:time:evening")
    builder.button(text="🔄 Оба", callback_data="assist:time:both")
    builder.button(text="⏭ Пропустить", callback_data="assist:skip")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 1, 2)
    return finalize_markup(builder)


def get_generic_frequency_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard for selecting habit frequency (generic).

    Returns:
        InlineKeyboardMarkup with frequency options, skip, and navigation.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📅 Каждый день",
        callback_data="assist:freq:daily",
    )
    builder.button(
        text="📆 Несколько раз в неделю",
        callback_data="assist:freq:several_per_week",
    )
    builder.button(
        text="📋 Раз в неделю",
        callback_data="assist:freq:once_per_week",
    )
    builder.button(text="⏭ Пропустить", callback_data="assist:skip")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 1, 1, 1, 2)
    return finalize_markup(builder)


def get_skip_only_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard with only a skip button for free-text questions.

    Returns:
        InlineKeyboardMarkup with skip, back, and cancel buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data="assist:skip")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(1, 2)
    return finalize_markup(builder)


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
    return finalize_markup(builder)


# =============================================================================
# Settings keyboards
# =============================================================================


def get_settings_menu_keyboard(
    lang: str = "ru",
    *,
    checkin_no_spam: bool = True,
    ask_auto_rollover: bool = False,
) -> InlineKeyboardMarkup:
    """Build the main settings menu keyboard.

    Args:
        lang: User language code (``ru`` / ``en``).
        checkin_no_spam: Current anti-spam setting (shown on toggle button).
        ask_auto_rollover: Current post-create rollover prompt setting.

    Returns:
        Inline keyboard with language, timezone, reminder_time,
        check_interval, toggles plus Back and Main menu.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("settings.btn_language", lang),
        callback_data="settings:language",
    )
    builder.button(
        text=t("settings.btn_timezone", lang),
        callback_data="settings:timezone",
    )
    builder.button(
        text=t("settings.btn_reminder", lang),
        callback_data="settings:reminder_time",
    )
    builder.button(
        text=t("settings.btn_interval", lang),
        callback_data="settings:check_interval",
    )
    no_spam_state = t("common.on", lang) if checkin_no_spam else t("common.off", lang)
    ask_state = t("common.on", lang) if ask_auto_rollover else t("common.off", lang)
    builder.button(
        text=t("settings.btn_no_spam", lang, state=no_spam_state),
        callback_data="settings:toggle_no_spam",
    )
    builder.button(
        text=t("settings.btn_ask_rollover", lang, state=ask_state),
        callback_data="settings:toggle_ask_rollover",
    )
    builder.button(text=t("common.back", lang), callback_data="nav:back")
    builder.button(
        text=t("common.main_menu_btn", lang),
        callback_data="nav:cancel",
    )
    builder.adjust(1, 1, 1, 1, 1, 1, 1, 1)
    return finalize_markup(builder)



def get_language_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Build the language selection keyboard (RU / EN only).

    Args:
        lang: User language code for navigation labels.

    Returns:
        Inline keyboard with RU and EN plus Back / Main menu.
    """
    languages = [
        ("RU", "settings:set_language:ru"),
        ("EN", "settings:set_language:en"),
    ]
    builder = InlineKeyboardBuilder()
    for label, data in languages:
        builder.button(text=label, callback_data=data)
    builder.button(text=t("common.back", lang), callback_data="settings:back")
    builder.button(
        text=t("common.main_menu_btn", lang),
        callback_data="nav:cancel",
    )
    builder.adjust(2, 1, 1)
    return finalize_markup(builder)


def get_timezone_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Build the timezone selection keyboard.

    Args:
        lang: User language code for navigation labels.

    Returns:
        Inline keyboard with major UTC offsets from -12 to +14.
    """
    timezones = [
        ("UTC-12", "settings:set_timezone:-12"),
        ("UTC-11", "settings:set_timezone:-11"),
        ("UTC-10", "settings:set_timezone:-10"),
        ("UTC-9", "settings:set_timezone:-9"),
        ("UTC-8", "settings:set_timezone:-8"),
        ("UTC-7", "settings:set_timezone:-7"),
        ("UTC-6", "settings:set_timezone:-6"),
        ("UTC-5", "settings:set_timezone:-5"),
        ("UTC-4", "settings:set_timezone:-4"),
        ("UTC-3", "settings:set_timezone:-3"),
        ("UTC-2", "settings:set_timezone:-2"),
        ("UTC-1", "settings:set_timezone:-1"),
        ("UTC+0", "settings:set_timezone:+0"),
        ("UTC+1", "settings:set_timezone:+1"),
        ("UTC+2", "settings:set_timezone:+2"),
        ("UTC+3", "settings:set_timezone:+3"),
        ("UTC+4", "settings:set_timezone:+4"),
        ("UTC+5", "settings:set_timezone:+5"),
        ("UTC+6", "settings:set_timezone:+6"),
        ("UTC+7", "settings:set_timezone:+7"),
        ("UTC+8", "settings:set_timezone:+8"),
        ("UTC+9", "settings:set_timezone:+9"),
        ("UTC+10", "settings:set_timezone:+10"),
        ("UTC+11", "settings:set_timezone:+11"),
        ("UTC+12", "settings:set_timezone:+12"),
        ("UTC+13", "settings:set_timezone:+13"),
        ("UTC+14", "settings:set_timezone:+14"),
    ]
    builder = InlineKeyboardBuilder()
    for label, data in timezones:
        builder.button(text=label, callback_data=data)
    builder.button(text=t("common.back", lang), callback_data="settings:back")
    builder.button(
        text=t("common.main_menu_btn", lang),
        callback_data="nav:cancel",
    )
    builder.adjust(4, 4, 4, 4, 4, 4, 3, 1, 1)
    return finalize_markup(builder)


def get_reminder_time_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Build the reminder time selection keyboard.

    Args:
        lang: User language code for navigation / disable labels.

    Returns:
        Inline keyboard with 24 hour slots (00:00–23:00) plus disable
        and navigation.
    """
    builder = InlineKeyboardBuilder()
    for hour in range(24):
        label = f"{hour:02d}:00"
        data = f"settings:set_reminder:{hour:02d}:00"
        builder.button(text=label, callback_data=data)
    builder.button(
        text=t("settings.reminder_disable", lang),
        callback_data="reminder:off",
    )
    builder.button(text=t("common.back", lang), callback_data="settings:back")
    builder.button(
        text=t("common.main_menu_btn", lang),
        callback_data="nav:cancel",
    )
    builder.adjust(6, 6, 6, 6, 1, 1, 1)
    return finalize_markup(builder)


def get_check_interval_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Build the check interval selection keyboard.

    Args:
        lang: User language code for option / navigation labels.

    Returns:
        Inline keyboard with interval options: 5, 10, 15, 20, 30, 45, 60 min.
    """
    minutes = [5, 10, 15, 20, 30, 45, 60]
    builder = InlineKeyboardBuilder()
    for n in minutes:
        builder.button(
            text=t("settings.interval_option", lang, n=n),
            callback_data=f"settings:set_interval:{n}",
        )
    builder.button(text=t("common.back", lang), callback_data="settings:back")
    builder.button(
        text=t("common.main_menu_btn", lang),
        callback_data="nav:cancel",
    )
    builder.adjust(2, 2, 2, 1, 1, 1)
    return finalize_markup(builder)



# ---------------------------------------------------------------------------
# Check-in keyboards — yes / mute / later / reschedule
# ---------------------------------------------------------------------------

_CHECKIN_SNOOZE_MINUTES: tuple[int, ...] = (15, 30, 45, 60)


def get_checkin_keyboard(task_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Build the main check-in prompt keyboard (4 actions).

    Args:
        task_id: ID of the task being checked.
        lang: User language code for button labels.

    Returns:
        InlineKeyboardMarkup with yes / mute / later / reschedule.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("checkin.btn_yes", lang),
        callback_data=f"checkin:yes:{task_id}",
    )
    builder.button(
        text=t("checkin.btn_mute", lang),
        callback_data=f"checkin:mute:{task_id}",
    )
    builder.button(
        text=t("checkin.btn_later", lang),
        callback_data=f"checkin:later:{task_id}",
    )
    builder.button(
        text=t("checkin.btn_reschedule", lang),
        callback_data=f"checkin:reschedule:{task_id}",
    )
    builder.adjust(1)
    return finalize_markup(builder)


def get_checkin_snooze_keyboard(
    task_id: int,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Build snooze duration keyboard (15/30/45/60 min + back).

    Args:
        task_id: ID of the task being snoozed.
        lang: User language code for button labels.

    Returns:
        InlineKeyboardMarkup with duration options and back.
    """
    builder = InlineKeyboardBuilder()
    for n in _CHECKIN_SNOOZE_MINUTES:
        builder.button(
            text=t("checkin.snooze_option", lang, n=n),
            callback_data=f"checkin:snooze:{task_id}:{n}",
        )
    builder.button(
        text=t("checkin.back", lang),
        callback_data=f"checkin:back:{task_id}",
    )
    builder.adjust(2, 2, 1)
    return finalize_markup(builder)


def get_checkin_reschedule_keyboard(
    task_id: int,
    slots: list[time],
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Build free-slot selection keyboard for rescheduling.

    Args:
        task_id: ID of the task being moved.
        slots: Free start times to offer.
        lang: User language code for the back button.

    Returns:
        InlineKeyboardMarkup with time buttons and back.
    """
    builder = InlineKeyboardBuilder()
    for slot in slots:
        label = slot.strftime("%H:%M")
        builder.button(
            text=label,
            callback_data=(
                f"checkin:move:{task_id}:{slot.hour:02d}:{slot.minute:02d}"
            ),
        )
    builder.button(
        text=t("checkin.back", lang),
        callback_data=f"checkin:back:{task_id}",
    )
    # 4 time buttons per row, then back alone
    n = len(slots)
    if n == 0:
        builder.adjust(1)
    else:
        rows = [4] * (n // 4)
        if n % 4:
            rows.append(n % 4)
        rows.append(1)
        builder.adjust(*rows)
    return finalize_markup(builder)



