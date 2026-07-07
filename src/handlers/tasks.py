"""Handlers for task creation, calendar navigation, schedule viewing,
task management, and editing."""

import logging
from datetime import date, time, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import Habit, Task, User
from src.db.session import get_db
from src.keyboards.inline import (
    get_cancel_input_keyboard,
    get_conflict_resolution_keyboard,
    get_day_keyboard,
    get_edit_task_field_keyboard,
    get_main_menu_keyboard,
    get_month_calendar_keyboard,
    get_schedule_management_keyboard,
    get_simple_schedule_keyboard,
    get_task_confirm_changes_keyboard,
    get_task_confirm_keyboard,
    get_task_delete_confirmation_keyboard,
    get_task_management_keyboard,
    get_tasks_completion_keyboard,
    get_time_selection_keyboard,
)
from src.services.habit_generator import lazy_generate_for_range
from src.states.fsm import ConflictFSM, EditTaskFSM, MainFSM, NewTaskFSM
from src.utils.conflict import is_time_slot_free

logger = logging.getLogger(__name__)

router = Router()
"""Router for task-related handlers (calendar, creation, schedule, manage, edit, delete, conflict)."""


# ===========================================================================
# Helper: resolve user ID from telegram_id
# ===========================================================================


async def _get_user_id(telegram_id: int, session) -> int | None:
    """Look up the internal user ID by Telegram ID."""
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
    show_management_buttons: bool = True,
    edit: bool = True,
) -> None:
    """Fetch and display the task schedule for a specific date.

    Args:
        show_management_buttons: If ``True``, each task has a ``task:manage``
            button.  If ``False``, only navigation buttons are shown.
        edit: If ``True``, edit the existing ``target`` message.
            If ``False``, send a new message (e.g. after a success notice).
    """
    await state.clear()
    await state.set_state(MainFSM.main_menu)

    send = target.edit_text if edit else target.answer

    async with get_db() as session:
        user_id = await _get_user_id(telegram_id, session)
        if user_id is None:
            await send(
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
        await send(
            "На этот день задач нет.",
            reply_markup=get_simple_schedule_keyboard(),
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

    keyboard = (
        get_schedule_management_keyboard(tasks)
        if show_management_buttons
        else get_simple_schedule_keyboard()
    )
    await send("\n".join(lines), reply_markup=keyboard)


# ===========================================================================
# Entry point — "✅ Новая задача" from main menu
# ===========================================================================


@router.callback_query(F.data == "main_menu:new_task")
async def start_new_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Start the task creation wizard by showing the calendar."""
    await callback.answer()
    today = date.today()
    await state.set_state(NewTaskFSM.select_date)
    await callback.message.edit_text(
        "📅 Выберите дату для задачи:",
        reply_markup=get_month_calendar_keyboard(today.year, today.month),
    )


# ===========================================================================
# Calendar month navigation
# ===========================================================================


@router.callback_query(F.data.startswith("calendar:month:"))
async def navigate_month(callback: CallbackQuery) -> None:
    """Switch the calendar to the previous or next month."""
    await callback.answer()
    parts = callback.data.split(":")
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
    """Handle a day selection on the calendar — branches by view_mode."""
    await callback.answer()
    iso_date = callback.data.split(":", 2)[2]
    selected = date.fromisoformat(iso_date)
    data = await state.get_data()
    view_mode = data.get("view_mode", False)

    if view_mode:
        # View schedule mode — show schedule with management buttons
        await state.update_data(view_mode=False)
        async with get_db() as session:
            user_id = await _get_user_id(callback.from_user.id, session)
            if user_id is not None:
                await lazy_generate_for_range(user_id, selected, days=7)

        await _show_schedule(
            telegram_id=callback.from_user.id,
            target=callback.message,
            schedule_date=selected,
            state=state,
            show_management_buttons=True,
        )
        return

    # Normal mode — add task or view schedule for day
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
    """Show schedule for the selected date then prompt for task title."""
    await callback.answer()
    iso_date = callback.data.split(":", 2)[2]
    selected = date.fromisoformat(iso_date)
    await state.update_data(task_date=selected.isoformat(), view_mode=False)

    # Show schedule first (read-only), then prompt for title.
    # NOTE: _show_schedule calls state.clear() internally, so we must
    # re-store FSM data after it.
    await _show_schedule(
        telegram_id=callback.from_user.id,
        target=callback.message,
        schedule_date=selected,
        state=state,
        show_management_buttons=False,
    )

    await state.update_data(task_date=selected.isoformat(), view_mode=False)
    await state.set_state(NewTaskFSM.title)
    await callback.message.answer(
        "📝 Введите название задачи (от 1 до 200 символов):",
        reply_markup=get_cancel_input_keyboard(),
    )


# ===========================================================================
# Step 1 — process the task title
# ===========================================================================


@router.message(NewTaskFSM.title)
async def process_task_title(message: Message, state: FSMContext) -> None:
    """Receive and validate the task title."""
    title = message.text.strip() if message.text else ""

    if not title or len(title) > 200:
        await message.answer(
            "⚠️ Название должно содержать от 1 до 200 символов. Попробуйте ещё раз:",
            reply_markup=get_cancel_input_keyboard(),
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
    """Store the selected start time and move to the end-time step."""
    await callback.answer()

    if callback.data == "time:null":
        await callback.message.edit_text(
            "⚠️ Для времени начала необходимо выбрать конкретное время.",
        )
        return

    time_str = callback.data.split(":", 1)[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        start_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.edit_text(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    await state.update_data(task_start_time=start_time.isoformat(timespec="minutes"))
    await state.set_state(NewTaskFSM.end_time)

    await callback.message.edit_text(
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
    """Store the selected end time (or None) and move to confirmation."""
    await callback.answer()

    data = await state.get_data()
    start_time_str: str = data.get("task_start_time", "")
    start_time = time.fromisoformat(start_time_str) if start_time_str else None

    if callback.data == "time:null":
        await state.update_data(task_end_time=None)
        await _show_task_confirm(callback, state)
        return

    time_str = callback.data.split(":", 1)[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        end_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.edit_text(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    if start_time is not None and end_time <= start_time:
        await callback.message.edit_text(
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
    """Show a summary of the task data and ask for confirmation."""
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

    await target.message.edit_text(summary, reply_markup=get_task_confirm_keyboard())


# ===========================================================================
# Step 4 — save the task (after confirmation)
# ===========================================================================


@router.callback_query(F.data == "task:save")
async def save_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Validate and persist the new task to the database."""
    await callback.answer()

    data = await state.get_data()
    task_date_str: str = data.get("task_date", "")
    task_title: str = data.get("task_title", "")
    start_str: str = data.get("task_start_time", "")
    end_str: str | None = data.get("task_end_time")

    if not task_date_str or not task_title or not start_str:
        await callback.message.edit_text(
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
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            await state.set_state(MainFSM.main_menu)
            return

        if not await is_time_slot_free(
            session, user_id, task_date, new_start_time, new_end_time
        ):
            await state.set_state(ConflictFSM.choose_action)
            await callback.message.edit_text(
                "⚠️ Обнаружен конфликт по времени!\n"
                "На выбранную дату и время уже есть задача.\n\n"
                "Выберите действие:",
                reply_markup=get_conflict_resolution_keyboard(),
            )
            return

        await _persist_task(session, user_id, task_date, task_title, new_start_time, new_end_time)

    await state.clear()
    await state.set_state(MainFSM.main_menu)

    await callback.message.answer(
        f"✅ Задача «{task_title}» успешно создана на {task_date.isoformat()}!",
    )
    await _show_schedule(
        telegram_id=telegram_id,
        target=callback.message,
        schedule_date=task_date,
        state=state,
        edit=False,
    )


async def _persist_task(
    session,
    user_id: int,
    task_date: date,
    task_title: str,
    start_time: time,
    end_time: time | None,
) -> Task:
    """Create and persist a Task row within an existing session."""
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
    """Force-add the task despite the time conflict."""
    await callback.answer()
    await _conflict_save_and_show(callback, state)


@router.callback_query(ConflictFSM.choose_action, F.data == "conflict:edit_schedule")
async def conflict_edit_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the schedule view so the user can delete conflicting tasks."""
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
    """Return to the task title step so the user can change task parameters."""
    await callback.answer()
    await state.set_state(NewTaskFSM.title)
    await callback.message.answer(
        "📝 Введите новое название задачи (от 1 до 200 символов):",
        reply_markup=get_cancel_input_keyboard(),
    )


async def _conflict_save_and_show(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Persist the task from FSM data (force save) and show the schedule."""
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
            await callback.message.edit_text(
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
        edit=False,
    )


# ===========================================================================
# View schedule — "📋 Просмотр расписания"
# ===========================================================================


@router.callback_query(F.data.startswith("task:view:"))
async def view_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the schedule (list of tasks) for a specific date."""
    await callback.answer()
    iso_date = callback.data.split(":", 2)[2]
    schedule_date = date.fromisoformat(iso_date)

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
# Task management — "task:manage:{id}" shows the management menu
# ===========================================================================


@router.callback_query(F.data.startswith("task:manage:"))
async def manage_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the task management keyboard for a specific task."""
    await callback.answer()
    task_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        # Determine habit linkage and modification status
        has_habit = task.habit_id is not None
        is_modified = False
        if has_habit:
            habit = await session.get(Habit, task.habit_id)
            if habit is not None:
                is_modified = (
                    task.start_time != habit.start_time
                    or task.end_time != habit.end_time
                )

    # Store original task data in FSM for potential reset/restore
    await state.update_data(
        edit_task_id=task_id,
        original_task_date=task.date.isoformat(),
        original_task_title=task.title,
        original_task_start_time=task.start_time.isoformat(timespec="minutes"),
        original_task_end_time=(
            task.end_time.isoformat(timespec="minutes") if task.end_time else None
        ),
    )
    await state.set_state(EditTaskFSM.choose_action)

    await callback.message.edit_text(
        f"Управление задачей «{task.title}»:\n"
        f"📅 {task.date.isoformat()} | "
        f"⏰ {task.start_time.strftime('%H:%M')}"
        + (f"–{task.end_time.strftime('%H:%M')}" if task.end_time else ", без окончания"),
        reply_markup=get_task_management_keyboard(
            task_id=task_id, has_habit=has_habit, is_modified=is_modified,
        ),
    )


# ===========================================================================
# Task deletion — "task:delete:{id}" shows confirmation prompt
# ===========================================================================


@router.callback_query(F.data.startswith("task:delete:"))
async def confirm_delete_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Show a confirmation prompt before deleting a task."""
    await callback.answer()
    task_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        task_date = task.date.isoformat()
        task_title = task.title

    await state.update_data(delete_task_date=task_date)
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить задачу «{task_title}» "
        f"на {task_date}?",
        reply_markup=get_task_delete_confirmation_keyboard(task_id),
    )


# ===========================================================================
# Task deletion — "task:confirm_delete:{id}" executes the deletion
# ===========================================================================


@router.callback_query(F.data.startswith("task:confirm_delete:"))
async def execute_delete_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete a task after user confirmation."""
    await callback.answer()
    task_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        task_date = task.date
        task_title = task.title
        await session.delete(task)
        await session.commit()

    await callback.message.answer(f"🗑 Задача «{task_title}» удалена.")
    await _show_schedule(
        telegram_id=callback.from_user.id,
        target=callback.message,
        schedule_date=task_date,
        state=state,
        edit=False,
    )


# ===========================================================================
# Task edit — enter field selection
# ===========================================================================


@router.callback_query(F.data.startswith("task:edit:"))
async def start_edit_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the field selection keyboard for editing a task."""
    await callback.answer()
    task_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        # Initialize pending values with current task data
        await state.update_data(
            edit_task_id=task_id,
            pending_title=task.title,
            pending_date=task.date.isoformat(),
            pending_start_time=task.start_time.isoformat(timespec="minutes"),
            pending_end_time=(
                task.end_time.isoformat(timespec="minutes") if task.end_time else None
            ),
            end_time_manually_set=False,
        )

    await state.set_state(EditTaskFSM.edit_field)
    await callback.message.edit_text(
        "Что вы хотите изменить в задаче?",
        reply_markup=get_edit_task_field_keyboard(),
    )


# ===========================================================================
# Edit field dispatchers
# ===========================================================================


@router.callback_query(
    EditTaskFSM.edit_field, F.data == "edit_task_field:title"
)
async def edit_task_title_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt the user to enter a new title."""
    await callback.answer()
    await state.set_state(EditTaskFSM.edit_title)
    await callback.message.answer(
        "📝 Введите новое название (от 1 до 200 символов):",
        reply_markup=get_cancel_input_keyboard(),
    )


@router.callback_query(
    EditTaskFSM.edit_field, F.data == "edit_task_field:date"
)
async def edit_task_date_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the calendar to select a new date."""
    await callback.answer()
    await state.set_state(EditTaskFSM.edit_date)
    today = date.today()
    await callback.message.edit_text(
        "📅 Выберите новую дату:",
        reply_markup=get_month_calendar_keyboard(today.year, today.month),
    )


@router.callback_query(
    EditTaskFSM.edit_field, F.data == "edit_task_field:start_time"
)
async def edit_task_start_time_prompt(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    """Show the time keyboard to select a new start time."""
    await callback.answer()
    await state.set_state(EditTaskFSM.edit_start_time)
    await callback.message.edit_text(
        "🕐 Выберите новое время начала:",
        reply_markup=get_time_selection_keyboard(),
    )


@router.callback_query(
    EditTaskFSM.edit_field, F.data == "edit_task_field:end_time"
)
async def edit_task_end_time_prompt(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    """Show the time keyboard to select a new end time."""
    await callback.answer()

    data = await state.get_data()
    pending_start_str = data.get("pending_start_time", "")
    min_time = time.fromisoformat(pending_start_str) if pending_start_str else None

    # Mark that the user is manually changing end_time
    await state.update_data(end_time_manually_set=True)
    await state.set_state(EditTaskFSM.edit_end_time)
    await callback.message.edit_text(
        "🕐 Выберите новое время окончания:",
        reply_markup=get_time_selection_keyboard(
            min_time=min_time, show_null_option=True,
        ),
    )


# ===========================================================================
# Apply title change (EditTaskFSM)
# ===========================================================================


@router.message(EditTaskFSM.edit_title)
async def apply_edit_task_title(message: Message, state: FSMContext) -> None:
    """Apply a new title to the task being edited."""
    title = message.text.strip() if message.text else ""

    if not title or len(title) > 200:
        await message.answer(
            "⚠️ Название должно содержать от 1 до 200 символов. Попробуйте ещё раз:",
            reply_markup=get_cancel_input_keyboard(),
        )
        return

    await state.update_data(pending_title=title)
    await state.set_state(EditTaskFSM.edit_field)
    await message.answer(
        f"✅ Название изменено на «{title}».\n"
        "Что вы хотите изменить в задаче?",
        reply_markup=get_edit_task_field_keyboard(),
    )


# ===========================================================================
# Apply date change (EditTaskFSM) via calendar
# ===========================================================================


@router.callback_query(
    EditTaskFSM.edit_date, F.data.startswith("calendar:day:"),
)
async def apply_edit_task_date(callback: CallbackQuery, state: FSMContext) -> None:
    """Apply a new date to the task being edited."""
    await callback.answer()
    iso_date = callback.data.split(":", 2)[2]
    selected = date.fromisoformat(iso_date)

    await state.update_data(pending_date=selected.isoformat())
    await state.set_state(EditTaskFSM.edit_field)
    await callback.message.edit_text(
        f"✅ Дата изменена на {selected.isoformat()}.\n"
        "Что вы хотите изменить в задаче?",
        reply_markup=get_edit_task_field_keyboard(),
    )


# ===========================================================================
# Apply start time change (EditTaskFSM) with auto-extension
# ===========================================================================


@router.callback_query(
    EditTaskFSM.edit_start_time, F.data.startswith("time:"), F.data != "time:null",
)
async def apply_edit_task_start_time(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    """Apply a new start time, automatically extending end_time."""
    await callback.answer()

    time_str = callback.data.split(":", 1)[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        new_start_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.edit_text(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    data = await state.get_data()
    old_start_str = data.get("pending_start_time", "")
    old_end_str = data.get("pending_end_time")
    end_time_manually_set: bool = data.get("end_time_manually_set", False)

    old_start = time.fromisoformat(old_start_str) if old_start_str else None
    old_end = time.fromisoformat(old_end_str) if old_end_str else None

    # Auto-extension: only if end_time was NOT manually set
    if not end_time_manually_set and old_start is not None and old_end is not None:
        # Calculate duration
        today_ref = date.today()
        old_dt_start = timedelta(
            hours=old_start.hour, minutes=old_start.minute,
        )
        old_dt_end = timedelta(
            hours=old_end.hour, minutes=old_end.minute,
        )
        if old_dt_end <= old_dt_start:
            old_dt_end += timedelta(days=1)  # Handle overnight

        duration = old_dt_end - old_dt_start
        new_dt_start = timedelta(
            hours=new_start_time.hour, minutes=new_start_time.minute,
        )
        new_dt_end = new_dt_start + duration

        # Check bounds: end must be <= 23:59
        max_end = timedelta(hours=23, minutes=59)
        if new_dt_end > max_end:
            await callback.message.edit_text(
                "⚠️ Выход за границы дня. "
                "Новое время окончания превышает 23:59.\n"
                "Пожалуйста, выберите более раннее время начала "
                "или измените время окончания вручную.",
                reply_markup=get_time_selection_keyboard(),
            )
            return

        new_end_hours = int(new_dt_end.total_seconds() // 3600)
        new_end_minutes = int((new_dt_end.total_seconds() % 3600) // 60)
        new_end_time = time(new_end_hours, new_end_minutes)
        await state.update_data(
            pending_start_time=new_start_time.isoformat(timespec="minutes"),
            pending_end_time=new_end_time.isoformat(timespec="minutes"),
        )

        await state.set_state(EditTaskFSM.edit_field)
        await callback.message.edit_text(
            f"✅ Время начала изменено на {new_start_time.strftime('%H:%M')}.\n"
            f"Время окончания автоматически сдвинуто на "
            f"{new_end_time.strftime('%H:%M')}.\n\n"
            "Что вы хотите изменить в задаче?",
            reply_markup=get_edit_task_field_keyboard(),
        )
        return

    # No auto-extension: just update start_time
    await state.update_data(
        pending_start_time=new_start_time.isoformat(timespec="minutes"),
    )

    await state.set_state(EditTaskFSM.edit_field)
    await callback.message.edit_text(
        f"✅ Время начала изменено на {new_start_time.strftime('%H:%M')}.\n"
        "Что вы хотите изменить в задаче?",
        reply_markup=get_edit_task_field_keyboard(),
    )


# ===========================================================================
# Apply end time change (EditTaskFSM)
# ===========================================================================


@router.callback_query(
    EditTaskFSM.edit_end_time, F.data.startswith("time:"),
)
async def apply_edit_task_end_time(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    """Apply a new end time to the task being edited."""
    await callback.answer()

    data = await state.get_data()
    pending_start_str = data.get("pending_start_time", "")
    start_time = time.fromisoformat(pending_start_str) if pending_start_str else None

    if callback.data == "time:null":
        await state.update_data(pending_end_time=None)
        await state.set_state(EditTaskFSM.edit_field)
        await callback.message.edit_text(
            "✅ Время окончания сброшено (без ограничения).\n"
            "Что вы хотите изменить в задаче?",
            reply_markup=get_edit_task_field_keyboard(),
        )
        return

    time_str = callback.data.split(":", 1)[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        new_end_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.edit_text(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    if start_time is not None and new_end_time <= start_time:
        await callback.message.edit_text(
            "⚠️ Время окончания должно быть позже времени начала. "
            "Выберите другое время:",
            reply_markup=get_time_selection_keyboard(
                min_time=start_time, show_null_option=True,
            ),
        )
        return

    await state.update_data(
        pending_end_time=new_end_time.isoformat(timespec="minutes"),
    )
    await state.set_state(EditTaskFSM.edit_field)
    await callback.message.edit_text(
        f"✅ Время окончания изменено на {new_end_time.strftime('%H:%M')}.\n"
        "Что вы хотите изменить в задаче?",
        reply_markup=get_edit_task_field_keyboard(),
    )


# ===========================================================================
# Reset task to habit template
# ===========================================================================


@router.callback_query(F.data.startswith("task:reset:"))
async def reset_task_to_habit(callback: CallbackQuery, state: FSMContext) -> None:
    """Reset the task's time to the linked habit's template."""
    await callback.answer()
    task_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        if task.habit_id is None:
            await callback.answer(
                "Эта задача не связана с привычкой.", show_alert=True,
            )
            return

        habit = await session.get(Habit, task.habit_id)
        if habit is None:
            await callback.answer(
                "Привычка не найдена.", show_alert=True,
            )
            return

        # Reset time to habit template; also carry over title/date from task
        await state.update_data(
            pending_title=task.title,
            pending_date=task.date.isoformat(),
            pending_start_time=habit.start_time.isoformat(timespec="minutes"),
            pending_end_time=(
                habit.end_time.isoformat(timespec="minutes")
                if habit.end_time else None
            ),
            end_time_manually_set=False,
        )
        has_habit = True
        is_modified = False

    await state.set_state(EditTaskFSM.choose_action)
    await callback.message.edit_text(
        f"🔄 Время задачи «{task.title}» сброшено к шаблону привычки.\n\n"
        f"Управление задачей «{task.title}»:",
        reply_markup=get_task_management_keyboard(
            task_id=task_id, has_habit=has_habit, is_modified=is_modified,
        ),
    )


# ===========================================================================
# Confirm changes — apply pending edits to DB
# ===========================================================================


@router.callback_query(F.data == "task:confirm_changes")
async def confirm_edit_changes(callback: CallbackQuery, state: FSMContext) -> None:
    """Apply all pending task changes to the database."""
    await callback.answer()

    data = await state.get_data()
    task_id: int = data.get("edit_task_id", 0)
    pending_title: str = data.get("pending_title", "")
    pending_date_str: str = data.get("pending_date", "")
    pending_start_str: str = data.get("pending_start_time", "")
    pending_end_str: str | None = data.get("pending_end_time")

    if not task_id or not pending_title or not pending_date_str or not pending_start_str:
        await callback.message.edit_text(
            "⚠️ Не хватает данных. Редактирование отменено.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        return

    pending_date = date.fromisoformat(pending_date_str)
    pending_start = time.fromisoformat(pending_start_str)
    pending_end = time.fromisoformat(pending_end_str) if pending_end_str else None
    telegram_id = callback.from_user.id

    async with get_db() as session:
        user_id = await _get_user_id(telegram_id, session)
        if user_id is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            await state.set_state(MainFSM.main_menu)
            return

        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        # Conflict check (excluding this task itself)
        if not await is_time_slot_free(
            session,
            user_id,
            pending_date,
            pending_start,
            pending_end,
            exclude_task_id=task_id,
        ):
            # Store pending edits and go to conflict resolution
            await state.set_state(ConflictFSM.choose_action)
            # For conflict resolution we need task_date/task_title/task_start_time/task_end_time
            await state.update_data(
                task_date=pending_date_str,
                task_title=pending_title,
                task_start_time=pending_start_str,
                task_end_time=pending_end_str,
            )
            await callback.message.edit_text(
                "⚠️ Обнаружен конфликт по времени!\n"
                "На выбранную дату и время уже есть другая задача.\n\n"
                "Выберите действие:",
                reply_markup=get_conflict_resolution_keyboard(),
            )
            return

        # Apply changes
        task.title = pending_title
        task.date = pending_date
        task.start_time = pending_start
        task.end_time = pending_end
        await session.commit()

    await state.clear()
    await state.set_state(MainFSM.main_menu)

    await callback.message.answer(
        f"✅ Задача «{pending_title}» успешно обновлена!",
    )
    await _show_schedule(
        telegram_id=telegram_id,
        target=callback.message,
        schedule_date=pending_date,
        state=state,
        edit=False,
    )


# ===========================================================================
# Navigation — Back button for NewTaskFSM, ConflictFSM, and EditTaskFSM
# ===========================================================================

_NEW_TASK_STATES = [
    NewTaskFSM.select_date,
    NewTaskFSM.title,
    NewTaskFSM.start_time,
    NewTaskFSM.end_time,
    NewTaskFSM.confirm,
]
_CONFLICT_STATES = [ConflictFSM.choose_action]
_EDIT_TASK_STATES = [
    EditTaskFSM.choose_action,
    EditTaskFSM.edit_field,
    EditTaskFSM.edit_title,
    EditTaskFSM.edit_date,
    EditTaskFSM.edit_start_time,
    EditTaskFSM.edit_end_time,
    EditTaskFSM.confirm_changes,
]


@router.callback_query(
    F.data == "nav:back",
    StateFilter(*(_NEW_TASK_STATES + _CONFLICT_STATES + _EDIT_TASK_STATES)),
)
async def handle_task_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate one step back in task creation, conflict, or edit flows."""
    await callback.answer()

    current_state = await state.get_state()

    # --- ConflictFSM back navigation ---
    if current_state == ConflictFSM.choose_action.state:
        # Check if we came from NewTaskFSM or EditTaskFSM
        data = await state.get_data()
        if data.get("edit_task_id"):
            # Came from edit flow — go back to confirm_changes equivalent
            await state.set_state(EditTaskFSM.edit_field)
            await callback.message.edit_text(
                "Что вы хотите изменить в задаче?",
                reply_markup=get_edit_task_field_keyboard(),
            )
            return
        else:
            # Came from new task creation
            await state.set_state(NewTaskFSM.confirm)
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
            await callback.message.edit_text(summary, reply_markup=get_task_confirm_keyboard())
            return

    # --- EditTaskFSM back navigation ---
    if current_state == EditTaskFSM.choose_action.state:
        # Back to schedule
        data = await state.get_data()
        date_str = data.get("original_task_date", date.today().isoformat())
        schedule_date = date.fromisoformat(date_str)
        await _show_schedule(
            telegram_id=callback.from_user.id,
            target=callback.message,
            schedule_date=schedule_date,
            state=state,
        )
        return

    if current_state == EditTaskFSM.edit_field.state:
        # Back to choose_action
        data = await state.get_data()
        task_id = data.get("edit_task_id")

        async with get_db() as session:
            user_id = await _get_user_id(callback.from_user.id, session)
            if user_id is not None:
                task = await session.get(Task, task_id)
                if task is not None:
                    has_habit = task.habit_id is not None
                    is_modified = False
                    if has_habit:
                        habit = await session.get(Habit, task.habit_id)
                        if habit is not None:
                            is_modified = (
                                task.start_time != habit.start_time
                                or task.end_time != habit.end_time
                            )

        await state.set_state(EditTaskFSM.choose_action)
        await callback.message.edit_text(
            f"Управление задачей «{task.title if task else '...'}»:",
            reply_markup=get_task_management_keyboard(
                task_id=task_id,
                has_habit=has_habit if task else False,
                is_modified=is_modified if task else False,
            ),
        )
        return

    if current_state in (
        EditTaskFSM.edit_title.state,
        EditTaskFSM.edit_date.state,
        EditTaskFSM.edit_start_time.state,
        EditTaskFSM.edit_end_time.state,
    ):
        await state.set_state(EditTaskFSM.edit_field)
        await callback.message.edit_text(
            "Что вы хотите изменить в задаче?",
            reply_markup=get_edit_task_field_keyboard(),
        )
        return

    # --- NewTaskFSM back navigation ---
    if current_state == NewTaskFSM.title.state:
        await state.set_state(NewTaskFSM.select_date)
        data = await state.get_data()
        iso = data.get("task_date", date.today().isoformat())
        target_date = date.fromisoformat(iso)
        await callback.message.edit_text(
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
            reply_markup=get_cancel_input_keyboard(),
        )
        return

    if current_state == NewTaskFSM.end_time.state:
        await state.set_state(NewTaskFSM.start_time)
        await callback.message.edit_text(
            "⏰ Выберите время начала задачи:",
            reply_markup=get_time_selection_keyboard(),
        )
        return

    if current_state == NewTaskFSM.confirm.state:
        await state.set_state(NewTaskFSM.end_time)
        fsm_data = await state.get_data()
        st_str = fsm_data.get("task_start_time")
        st = time.fromisoformat(st_str) if st_str else None
        await callback.message.edit_text(
            "⏰ Выберите время окончания задачи:",
            reply_markup=get_time_selection_keyboard(
                min_time=st, show_null_option=True
            ),
        )
        return

    if current_state == NewTaskFSM.select_date.state:
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            "🏠 Главное меню бота\nВыберите действие:",
            reply_markup=get_main_menu_keyboard(),
        )
        return


# ===========================================================================
# Navigation — Cancel button for NewTaskFSM, ConflictFSM, and EditTaskFSM
# ===========================================================================


@router.callback_query(
    F.data == "nav:cancel",
    StateFilter(*(_NEW_TASK_STATES + _CONFLICT_STATES + _EDIT_TASK_STATES)),
)
async def handle_task_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the current wizard/flow and return to the main menu."""
    await callback.answer()

    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        "❌ Действие отменено.",
        reply_markup=get_main_menu_keyboard(),
    )


# ===========================================================================
# "📅 Посмотреть расписание" — calendar-based schedule viewer
# ===========================================================================


@router.callback_query(F.data == "main_menu:view_schedule")
async def view_schedule_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Open the calendar so the user can pick a date and view its schedule."""
    await callback.answer()
    await state.update_data(view_mode=True)
    today = date.today()
    await state.set_state(NewTaskFSM.select_date)
    await callback.message.edit_text(
        "📅 Выберите дату для просмотра расписания:",
        reply_markup=get_month_calendar_keyboard(today.year, today.month),
    )


# ===========================================================================
# "Посмотреть список дел на сегодня" — text-only schedule for today
# ===========================================================================


@router.callback_query(F.data == "main_menu:today_tasks")
async def today_tasks(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the task list for today (text only, no completion buttons)."""
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
# "Отметить выполненные дела" — toggle-completion mode
# ===========================================================================


@router.callback_query(F.data == "main_menu:complete_tasks")
async def complete_tasks_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """Enter task-completion mode: show today's tasks as toggle buttons."""
    await callback.answer()
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    today = date.today()

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text(
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
        await callback.message.edit_text(
            "На сегодня задач нет.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    await callback.message.edit_text(
        "📅 Отметьте выполненные задачи:",
        reply_markup=get_tasks_completion_keyboard(tasks),
    )


# ===========================================================================
# Task toggle — flip is_completed for a task
# ===========================================================================


@router.callback_query(F.data.startswith("task:toggle:"))
async def toggle_task_completion(callback: CallbackQuery) -> None:
    """Toggle the is_completed flag for a task."""
    await callback.answer()
    task_id = int(callback.data.split(":")[2])
    today = date.today()

    async with get_db() as session:
        user_id = await _get_user_id(callback.from_user.id, session)
        if user_id is None:
            await callback.message.edit_text("⚠️ Пользователь не найден.")
            return

        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None or task.user_id != user_id:
            await callback.answer("⛔ Задача не найдена или недоступна.", show_alert=True)
            return

        task.is_completed = not task.is_completed
        await session.commit()

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