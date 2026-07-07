"""Handlers for task creation, calendar navigation, and schedule viewing."""

import logging
from datetime import date, time

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select

from src.db.models import Task, User
from src.db.session import get_db
from src.keyboards.inline import (
    get_conflict_resolution_keyboard,
    get_day_keyboard,
    get_main_menu_keyboard,
    get_month_calendar_keyboard,
    get_schedule_with_delete_keyboard,
    get_task_confirm_keyboard,
    get_task_delete_confirmation_keyboard,
    get_tasks_completion_keyboard,
    get_time_selection_keyboard,
)
from src.services.habit_generator import lazy_generate_for_range
from src.states.fsm import ConflictFSM, MainFSM, NewTaskFSM
from src.utils.conflict import is_time_slot_free

logger = logging.getLogger(__name__)

router = Router()
"""Router for task-related handlers (calendar, creation, schedule, delete, conflict)."""


# ===========================================================================
# Helper: resolve user ID from telegram_id
# ===========================================================================


async def _get_user_id(telegram_id: int, session) -> int | None:
    """Look up the internal user ID by Telegram ID.

    Args:
        telegram_id: Telegram user identifier.
        session: Active database session.

    Returns:
        The ``User.id`` or ``None`` if the user was not found.
    """
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    return user.id if user else None


# ===========================================================================
# Helper: show schedule for a given date
# ===========================================================================


async def _show_schedule(
    *,
    telegram_id: int,
    target: Message,
    schedule_date: date,
    state: FSMContext,
) -> None:
    """Fetch and display the task schedule for a specific date.

    Clears the FSM state and sets ``MainFSM.main_menu``.

    Args:
        telegram_id: Telegram ID of the user.
        target: The message to reply to.
        schedule_date: The date to show tasks for.
        state: FSM context for the current user.
    """
    await state.clear()
    await state.set_state(MainFSM.main_menu)

    async with get_db() as session:
        user_id = await _get_user_id(telegram_id, session)
        if user_id is None:
            await target.answer(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        stmt = (
            select(Task)
            .where(Task.user_id == user_id, Task.date == schedule_date)
            .order_by(Task.start_time)
        )
        result = await session.execute(stmt)
        tasks = result.scalars().all()

    if not tasks:
        await target.answer(
            "На этот день задач нет.",
            reply_markup=get_day_keyboard(schedule_date),
        )
        return

    lines = [f"📅 Расписание на {schedule_date.isoformat()}:"]
    for i, task in enumerate(tasks, start=1):
        status = "✅" if task.is_completed else "⬜"
        if task.end_time is None:
            time_str = f"{task.start_time.strftime('%H:%M')}, без окончания"
        else:
            time_str = (
                f"{task.start_time.strftime('%H:%M')}"
                f"–{task.end_time.strftime('%H:%M')}"
            )
        lines.append(f"{i}. {status} {task.title} ({time_str})")

    await target.answer(
        "\n".join(lines),
        reply_markup=get_schedule_with_delete_keyboard(tasks),
    )


# ===========================================================================
# Entry point — "✅ Новая задача" from main menu
# ===========================================================================


@router.callback_query(F.data == "main_menu:new_task")
async def start_new_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Start the task creation wizard by showing the calendar.

    Args:
        callback: Incoming callback query from the main menu button.
        state: FSM context for the current user.
    """
    await callback.answer()
    today = date.today()
    await state.set_state(NewTaskFSM.select_date)
    await callback.message.answer(
        "📅 Выберите дату для задачи:",
        reply_markup=get_month_calendar_keyboard(today.year, today.month),
    )


# ===========================================================================
# Calendar month navigation
# ===========================================================================


@router.callback_query(F.data.startswith("calendar:month:"))
async def navigate_month(callback: CallbackQuery) -> None:
    """Switch the calendar to the previous or next month.

    Parses ``calendar:month:YYYY:MM`` from the callback data and renders
    the corresponding month grid.

    Args:
        callback: Incoming callback query from the month navigation button.
    """
    await callback.answer()
    parts = callback.data.split(":")
    # format: calendar:month:YYYY:MM
    year = int(parts[2])
    month = int(parts[3])
    await callback.message.edit_text(
        "📅 Выберите дату для задачи:",
        reply_markup=get_month_calendar_keyboard(year, month),
    )


# ===========================================================================
# Calendar day selection
# ===========================================================================


@router.callback_query(F.data.startswith("calendar:day:"))
async def select_day(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle a day selection on the calendar.

    Parses the ISO date from the callback and shows the day actions
    keyboard (add task / view schedule).

    Args:
        callback: Incoming callback query from a calendar day button.
        state: FSM context for the current user.
    """
    await callback.answer()
    # "calendar:day:2026-07-15" → "2026-07-15"
    iso_date = callback.data.split(":", 2)[2]
    selected = date.fromisoformat(iso_date)
    await state.update_data(task_date=iso_date)
    await state.set_state(NewTaskFSM.select_date)
    await callback.message.edit_text(
        f"📅 Выбран день: {iso_date}\nЧто вы хотите сделать?",
        reply_markup=get_day_keyboard(selected),
    )


# ===========================================================================
# Add task — "📅 Добавить задачу"
# ===========================================================================


@router.callback_query(F.data.startswith("task:add:"))
async def add_task_prompt_title(callback: CallbackQuery, state: FSMContext) -> None:
    """Start entering a task title for the given date.

    Parses the date from the callback, stores it in FSM, transitions to
    ``NewTaskFSM.title``, and asks for the task name.

    Args:
        callback: Incoming callback query from the day keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    # "task:add:2026-07-15" → "2026-07-15"
    iso_date = callback.data.split(":", 2)[2]
    selected = date.fromisoformat(iso_date)
    await state.update_data(task_date=selected.isoformat())
    await state.set_state(NewTaskFSM.title)
    await callback.message.answer(
        "📝 Введите название задачи (от 1 до 200 символов):",
    )


# ===========================================================================
# Step 1 — process the task title
# ===========================================================================


@router.message(NewTaskFSM.title)
async def process_task_title(message: Message, state: FSMContext) -> None:
    """Receive and validate the task title.

    Strips whitespace and checks that the title is between 1 and 200
    characters.  On success, stores it in FSM and moves to
    ``NewTaskFSM.start_time``.

    Args:
        message: Incoming text message with the task title.
        state: FSM context for the current user.
    """
    title = message.text.strip() if message.text else ""

    if not title or len(title) > 200:
        await message.answer(
            "⚠️ Название должно содержать от 1 до 200 символов. Попробуйте ещё раз:",
        )
        return

    await state.update_data(task_title=title)
    await state.set_state(NewTaskFSM.start_time)

    await message.answer(
        "⏰ Выберите время начала задачи:",
        reply_markup=get_time_selection_keyboard(),
    )


# ===========================================================================
# Step 2 — process the start time
# ===========================================================================


@router.callback_query(NewTaskFSM.start_time, F.data.startswith("time:"))
async def process_task_start_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Store the selected start time and move to the end-time step.

    Only real time values are accepted (``time:null`` is NOT allowed
    for start time).

    Args:
        callback: Incoming callback query from the time keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    # Reject time:null for start time
    if callback.data == "time:null":
        await callback.message.answer(
            "⚠️ Для времени начала необходимо выбрать конкретное время.",
        )
        return

    time_str = callback.data.split(":", 1)[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        start_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.answer(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    await state.update_data(task_start_time=start_time.isoformat(timespec="minutes"))
    await state.set_state(NewTaskFSM.end_time)

    await callback.message.answer(
        "⏰ Выберите время окончания задачи:",
        reply_markup=get_time_selection_keyboard(
            min_time=start_time, show_null_option=True
        ),
    )


# ===========================================================================
# Step 3 — process the end time
# ===========================================================================


@router.callback_query(NewTaskFSM.end_time, F.data.startswith("time:"))
async def process_task_end_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Store the selected end time (or ``None``) and move to confirmation.

    Validates that the end time is strictly after the start time (unless
    ``time:null`` is chosen).

    Args:
        callback: Incoming callback query from the time keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    data = await state.get_data()
    start_time_str: str = data.get("task_start_time", "")
    start_time = time.fromisoformat(start_time_str) if start_time_str else None

    # Special case: "Без времени" button
    if callback.data == "time:null":
        await state.update_data(task_end_time=None)
        await _show_task_confirm(callback, state)
        return

    time_str = callback.data.split(":", 1)[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        end_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.answer(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    if start_time is not None and end_time <= start_time:
        await callback.message.answer(
            "⚠️ Время окончания должно быть позже времени начала. "
            "Выберите другое время:",
            reply_markup=get_time_selection_keyboard(
                min_time=start_time, show_null_option=True
            ),
        )
        return

    await state.update_data(task_end_time=end_time.isoformat(timespec="minutes"))
    await _show_task_confirm(callback, state)


async def _show_task_confirm(
    target: CallbackQuery,
    state: FSMContext,
) -> None:
    """Show a summary of the task data and ask for confirmation.

    Args:
        target: The callback query to respond to.
        state: FSM context for the current user.
    """
    data = await state.get_data()
    task_date = data.get("task_date", "—")
    task_title = data.get("task_title", "—")
    start_str = data.get("task_start_time", "—")
    end_str = data.get("task_end_time")

    if end_str is None:
        time_display = f"{start_str} (без окончания)"
    else:
        time_display = f"{start_str} – {end_str}"

    await state.set_state(NewTaskFSM.confirm)

    summary = (
        "📋 Подтвердите создание задачи:\n\n"
        f"📅 Дата: {task_date}\n"
        f"📝 Название: {task_title}\n"
        f"⏰ Время: {time_display}"
    )

    await target.message.answer(summary, reply_markup=get_task_confirm_keyboard())


# ===========================================================================
# Step 4 — save the task (after confirmation)
# ===========================================================================


@router.callback_query(F.data == "task:save")
async def save_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Validate and persist the new task to the database.

    Checks for time conflicts with existing tasks on the same date before
    saving.  If a conflict is detected, offers resolution options via
    ``ConflictFSM.choose_action``.

    Args:
        callback: Incoming callback query from the confirm keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    data = await state.get_data()
    task_date_str: str = data.get("task_date", "")
    task_title: str = data.get("task_title", "")
    start_str: str = data.get("task_start_time", "")
    end_str: str | None = data.get("task_end_time")

    if not task_date_str or not task_title or not start_str:
        await callback.message.answer(
            "⚠️ Произошла ошибка. Не хватает данных. "
            "Начните создание задачи заново.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        return

    task_date = date.fromisoformat(task_date_str)
    new_start_time = time.fromisoformat(start_str)
    new_end_time = time.fromisoformat(end_str) if end_str else None
    telegram_id = callback.from_user.id

    async with get_db() as session:
        user_id = await _get_user_id(telegram_id, session)
        if user_id is None:
            await callback.message.answer(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            await state.set_state(MainFSM.main_menu)
            return

        # --- Conflict detection ---
        if not await is_time_slot_free(
            session, user_id, task_date, new_start_time, new_end_time
        ):
            # Store task data in FSM and offer resolution options
            await state.set_state(ConflictFSM.choose_action)
            await callback.message.answer(
                "⚠️ Обнаружен конфликт по времени!\n"
                "На выбранную дату и время уже есть задача.\n\n"
                "Выберите действие:",
                reply_markup=get_conflict_resolution_keyboard(),
            )
            return

        # --- Save ---
        await _persist_task(session, user_id, task_date, task_title, new_start_time, new_end_time)

    await state.clear()
    await state.set_state(MainFSM.main_menu)

    # Show success and the updated schedule
    await callback.message.answer(
        f"✅ Задача «{task_title}» успешно создана на {task_date.isoformat()}!",
    )
    await _show_schedule(
        telegram_id=telegram_id,
        target=callback.message,
        schedule_date=task_date,
        state=state,
    )


async def _persist_task(
    session,
    user_id: int,
    task_date: date,
    task_title: str,
    start_time: time,
    end_time: time | None,
) -> Task:
    """Create and persist a Task row within an existing session.

    Args:
        session: Active database session.
        user_id: Internal user ID.
        task_date: Task date.
        task_title: Task title.
        start_time: Task start time.
        end_time: Task end time (may be None).

    Returns:
        The newly created Task ORM object.
    """
    task = Task(
        user_id=user_id,
        habit_id=None,
        title=task_title,
        date=task_date,
        start_time=start_time,
        end_time=end_time,
        is_completed=False,
        is_placeholder=False,
    )
    session.add(task)
    await session.commit()
    return task


# ===========================================================================
# Conflict resolution handlers
# ===========================================================================


@router.callback_query(ConflictFSM.choose_action, F.data == "conflict:force_add")
async def conflict_force_add(callback: CallbackQuery, state: FSMContext) -> None:
    """Force-add the task despite the time conflict.

    Reads the pending task data from FSM, persists it ignoring any
    conflicts, and shows the updated schedule.

    Args:
        callback: Incoming callback query from the conflict keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    await _conflict_save_and_show(callback, state)


@router.callback_query(ConflictFSM.choose_action, F.data == "conflict:edit_schedule")
async def conflict_edit_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the schedule view so the user can delete conflicting tasks.

    Args:
        callback: Incoming callback query from the conflict keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    data = await state.get_data()
    task_date_str: str = data.get("task_date", date.today().isoformat())
    schedule_date = date.fromisoformat(task_date_str)

    await _show_schedule(
        telegram_id=callback.from_user.id,
        target=callback.message,
        schedule_date=schedule_date,
        state=state,
    )


@router.callback_query(ConflictFSM.choose_action, F.data == "conflict:edit_task")
async def conflict_edit_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the task title step so the user can change task parameters.

    Args:
        callback: Incoming callback query from the conflict keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.set_state(NewTaskFSM.title)
    await callback.message.answer(
        "📝 Введите новое название задачи (от 1 до 200 символов):",
    )


async def _conflict_save_and_show(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Persist the task from FSM data (force save) and show the schedule.

    Args:
        callback: Incoming callback query from the conflict keyboard.
        state: FSM context for the current user.
    """
    data = await state.get_data()
    task_date_str: str = data.get("task_date", "")
    task_title: str = data.get("task_title", "")
    start_str: str = data.get("task_start_time", "")
    end_str: str | None = data.get("task_end_time")

    task_date = date.fromisoformat(task_date_str)
    new_start_time = time.fromisoformat(start_str)
    new_end_time = time.fromisoformat(end_str) if end_str else None
    telegram_id = callback.from_user.id

    async with get_db() as session:
        user_id = await _get_user_id(telegram_id, session)
        if user_id is None:
            await callback.message.answer(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            await state.set_state(MainFSM.main_menu)
            return

        await _persist_task(session, user_id, task_date, task_title, new_start_time, new_end_time)

    await state.clear()
    await state.set_state(MainFSM.main_menu)

    await callback.message.answer(
        f"✅ Задача «{task_title}» добавлена (с перекрытием) на {task_date.isoformat()}!",
    )
    await _show_schedule(
        telegram_id=telegram_id,
        target=callback.message,
        schedule_date=task_date,
        state=state,
    )


# ===========================================================================
# View schedule — "📋 Просмотр расписания"
# ===========================================================================


@router.callback_query(F.data.startswith("task:view:"))
async def view_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the schedule (list of tasks) for a specific date.

    Args:
        callback: Incoming callback query from the day keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    # "task:view:2026-07-15" → "2026-07-15"
    iso_date = callback.data.split(":", 2)[2]
    schedule_date = date.fromisoformat(iso_date)

    # Lazy-generate tasks for this date + 6 more days
    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is not None:
            await lazy_generate_for_range(user_id, schedule_date, days=7)

    await _show_schedule(
        telegram_id=callback.from_user.id,
        target=callback.message,
        schedule_date=schedule_date,
        state=state,
    )


# ===========================================================================
# Task deletion — "task:delete:{id}" shows confirmation prompt
# ===========================================================================


@router.callback_query(F.data.startswith("task:delete:"))
async def confirm_delete_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Show a confirmation prompt before deleting a task.

    Args:
        callback: Incoming callback query from the schedule keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    task_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.answer(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

    # Store the date for redisplay after deletion
    await state.update_data(delete_task_date=task.date.isoformat())
    await callback.message.answer(
        f"Вы уверены, что хотите удалить задачу «{task.title}» "
        f"на {task.date.isoformat()}?",
        reply_markup=get_task_delete_confirmation_keyboard(task_id),
    )


# ===========================================================================
# Task deletion — "task:confirm_delete:{id}" executes the deletion
# ===========================================================================


@router.callback_query(F.data.startswith("task:confirm_delete:"))
async def execute_delete_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete a task after user confirmation.

    Args:
        callback: Incoming callback query from the confirmation keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    task_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.answer(
                "⚠️ Пользователь не найден.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        task_date = task.date
        task_title = task.title
        await session.delete(task)
        await session.commit()

    await callback.message.answer(f"🗑 Задача «{task_title}» удалена.")

    # Re-show schedule with updated list
    await _show_schedule(
        telegram_id=callback.from_user.id,
        target=callback.message,
        schedule_date=task_date,
        state=state,
    )


# ===========================================================================
# Navigation — Back button for NewTaskFSM states
# ===========================================================================

# Build a filter that matches any NewTaskFSM state
_NEW_TASK_STATES = [
    NewTaskFSM.select_date,
    NewTaskFSM.title,
    NewTaskFSM.start_time,
    NewTaskFSM.end_time,
    NewTaskFSM.confirm,
]
_CONFLICT_STATES = [ConflictFSM.choose_action]


@router.callback_query(
    F.data == "nav:back",
    StateFilter(*(_NEW_TASK_STATES + _CONFLICT_STATES)),
)
async def handle_task_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate one step back in the task creation wizard or conflict flow.

    Determines the current NewTaskFSM state and moves to the previous
    step.  Only triggers for ``NewTaskFSM`` states — other routers
    handle ``nav:back`` for their own states.

    Args:
        callback: Incoming callback query from the back button.
        state: FSM context for the current user.
    """
    await callback.answer()

    current_state = await state.get_state()

    # --- ConflictFSM back navigation ---
    if current_state == ConflictFSM.choose_action.state:
        await state.set_state(NewTaskFSM.confirm)
        data = await state.get_data()
        task_date = data.get("task_date", "—")
        task_title = data.get("task_title", "—")
        start_str = data.get("task_start_time", "—")
        end_str = data.get("task_end_time")
        if end_str is None:
            time_display = f"{start_str} (без окончания)"
        else:
            time_display = f"{start_str} – {end_str}"
        summary = (
            "📋 Подтвердите создание задачи:\n\n"
            f"📅 Дата: {task_date}\n"
            f"📝 Название: {task_title}\n"
            f"⏰ Время: {time_display}"
        )
        await callback.message.answer(summary, reply_markup=get_task_confirm_keyboard())
        return

    # --- NewTaskFSM back navigation ---
    if current_state == NewTaskFSM.title.state:
        # Back from title → go to calendar
        await state.set_state(NewTaskFSM.select_date)
        data = await state.get_data()
        iso = data.get("task_date", date.today().isoformat())
        target_date = date.fromisoformat(iso)
        await callback.message.answer(
            "📅 Выберите дату для задачи:",
            reply_markup=get_month_calendar_keyboard(
                target_date.year, target_date.month
            ),
        )
        return

    if current_state == NewTaskFSM.start_time.state:
        await state.set_state(NewTaskFSM.title)
        await callback.message.answer(
            "📝 Введите название задачи (от 1 до 200 символов):",
        )
        return

    if current_state == NewTaskFSM.end_time.state:
        await state.set_state(NewTaskFSM.start_time)
        await callback.message.answer(
            "⏰ Выберите время начала задачи:",
            reply_markup=get_time_selection_keyboard(),
        )
        return

    if current_state == NewTaskFSM.confirm.state:
        await state.set_state(NewTaskFSM.end_time)
        fsm_data = await state.get_data()
        st_str = fsm_data.get("task_start_time")
        st = time.fromisoformat(st_str) if st_str else None
        await callback.message.answer(
            "⏰ Выберите время окончания задачи:",
            reply_markup=get_time_selection_keyboard(
                min_time=st, show_null_option=True
            ),
        )
        return

    if current_state == NewTaskFSM.select_date.state:
        # Back from select_date → return to main menu
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await callback.message.answer(
            "🏠 Главное меню бота\nВыберите действие:",
            reply_markup=get_main_menu_keyboard(),
        )
        return


# ===========================================================================
# Navigation — Cancel button for NewTaskFSM states and ConflictFSM
# ===========================================================================


@router.callback_query(
    F.data == "nav:cancel",
    StateFilter(*(_NEW_TASK_STATES + _CONFLICT_STATES)),
)
async def handle_task_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the task creation wizard and return to the main menu.

    Only triggers for ``NewTaskFSM`` and ``ConflictFSM`` states — other
    routers handle ``nav:cancel`` for their own states.

    Args:
        callback: Incoming callback query from the cancel button.
        state: FSM context for the current user.
    """
    await callback.answer()

    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.answer(
        "❌ Создание задачи отменено.",
        reply_markup=get_main_menu_keyboard(),
    )


# ===========================================================================
# "Посмотреть список дел на сегодня" — text-only schedule for today
# ===========================================================================


@router.callback_query(F.data == "main_menu:today_tasks")
async def today_tasks(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the task list for today (text only, no completion buttons).

    Triggers lazy generation for the next 7 days, then delegates to
    ``_show_schedule`` which renders status icons (✅/⬜) and times.

    Args:
        callback: Incoming callback query from the main menu button.
        state: FSM context for the current user.
    """
    await callback.answer()
    today = date.today()

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is not None:
            await lazy_generate_for_range(user_id, today, days=7)

    await _show_schedule(
        telegram_id=callback.from_user.id,
        target=callback.message,
        schedule_date=today,
        state=state,
    )


# ===========================================================================
# "Отметить выполненные задачи за сегодня" — toggle-completion mode
# ===========================================================================


@router.callback_query(F.data == "main_menu:complete_tasks")
async def complete_tasks_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """Enter task-completion mode: show today's tasks as toggle buttons.

    Each task is rendered as an inline button whose text includes a
    status icon (✅/⬜).  Tapping the button fires ``task:toggle:{id}``.

    Args:
        callback: Incoming callback query from the main menu button.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    today = date.today()

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.answer(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        await lazy_generate_for_range(user_id, today, days=7)

        stmt = (
            select(Task)
            .where(Task.user_id == user_id, Task.date == today)
            .order_by(Task.start_time)
        )
        result = await session.execute(stmt)
        tasks = result.scalars().all()

    if not tasks:
        await callback.message.answer(
            "На сегодня задач нет.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    await callback.message.answer(
        "📅 Отметьте выполненные задачи:",
        reply_markup=get_tasks_completion_keyboard(tasks),
    )


# ===========================================================================
# Task toggle — flip is_completed for a task
# ===========================================================================


@router.callback_query(F.data.startswith("task:toggle:"))
async def toggle_task_completion(callback: CallbackQuery) -> None:
    """Toggle the ``is_completed`` flag for a task.

    Parses ``task:toggle:{task_id}``, verifies ownership, flips
    ``is_completed``, and updates the inline keyboard in place.

    Args:
        callback: Incoming callback query from a task toggle button.
    """
    await callback.answer()
    task_id = int(callback.data.split(":")[2])
    today = date.today()

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден.",
            )
            return

        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        task.is_completed = not task.is_completed
        await session.commit()

        # Reload today's tasks to rebuild the keyboard
        stmt = (
            select(Task)
            .where(Task.user_id == user_id, Task.date == today)
            .order_by(Task.start_time)
        )
        result = await session.execute(stmt)
        tasks = result.scalars().all()

    await callback.message.edit_reply_markup(
        reply_markup=get_tasks_completion_keyboard(tasks),
    )