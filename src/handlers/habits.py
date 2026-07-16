"""Handlers for habit creation, listing, editing, and deletion."""

import logging
from datetime import time

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select

from src.db.models import Habit, Task, User
from src.db.session import get_db
from src.keyboards.inline import (
    get_cancel_input_keyboard,
    get_delete_confirmation_keyboard,
    get_edit_field_keyboard,
    get_frequency_keyboard,
    get_habit_conflict_resolution_keyboard,
    get_main_menu_keyboard,
    get_minute_selection_keyboard,
    get_time_selection_keyboard,
)
from src.services.habit_generator import generate_tasks_for_habit
from src.states.fsm import (
    ConflictHabitFSM,
    EditHabitFSM,
    HabitFSM,
    MainFSM,
    NewHabitFSM,
)
from src.utils.conflict import (
    _days_display,
    _freq_day_overlap,
    check_habit_conflicts,
)
from src.utils.keyboard_width import finalize_markup
from src.utils.time_picker import PENDING_HOUR_KEY, parse_time_callback



logger = logging.getLogger(__name__)

router = Router()
"""Router for habit-related handlers."""

FREQ_LABELS: dict[str, str] = {
    "daily": "📅 Ежедневно",
    "weekdays": "📆 По будням",
    "weekends": "🎉 По выходным",
}

# ---------------------------------------------------------------------------
# State lists for back/cancel handlers — used with StateFilter
# ---------------------------------------------------------------------------

_HABIT_CANCEL_STATES = [
    NewHabitFSM.title,
    NewHabitFSM.start_time,
    NewHabitFSM.end_time,
    NewHabitFSM.frequency,
    EditHabitFSM.choose_field,
    EditHabitFSM.title,
    EditHabitFSM.start_time,
    EditHabitFSM.end_time,
    EditHabitFSM.frequency,
    EditHabitFSM.confirm_delete,
    ConflictHabitFSM.choose_action,
    HabitFSM.view_list,
    HabitFSM.interact_list,
    HabitFSM.manage_single,
]


async def _show_habit_list(
    *,
    telegram_id: int,
    target: Message,
    state: FSMContext,
) -> None:
    """Fetch and display the user's habit list with an «Интерактировать» button."""
    await state.clear()
    await state.set_state(HabitFSM.view_list)

    async with get_db() as session:
        stmt = (
            select(Habit)
            .join(User)
            .where(User.telegram_id == telegram_id)
            .order_by(Habit.id)
        )
        result = await session.execute(stmt)
        habits = result.scalars().all()

    if not habits:
        await target.edit_text(
            "У вас пока нет привычек.\nСоздайте первую через ➕ Создать привычку!",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.set_state(MainFSM.main_menu)
        return

    lines = ["📋 Ваши привычки:"]
    for i, habit in enumerate(habits, start=1):
        if habit.end_time is None:
            time_str = f"{habit.start_time.strftime('%H:%M')}, без ограничения"
        else:
            time_str = (
                f"{habit.start_time.strftime('%H:%M')}"
                f"–{habit.end_time.strftime('%H:%M')}"
            )
        freq = FREQ_LABELS.get(habit.frequency, habit.frequency)
        lines.append(f"{i}. {habit.title} ({time_str}, {freq})")

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Интерактировать", callback_data="habits:interact")
    builder.button(text="🏠 В главное меню", callback_data="nav:cancel")
    builder.adjust(2)
    await target.edit_text("\n".join(lines), reply_markup=finalize_markup(builder))



def _build_habit_conflict_message(
    title: str,
    start_time: time,
    end_time: time | None,
    frequency: str,
    conflicting: list[Habit],
) -> str:
    """Build a user-friendly message listing conflicting habits."""
    time_display = (
        f"{start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}"
        if end_time
        else f"{start_time.strftime('%H:%M')}, без окончания"
    )
    freq_label = FREQ_LABELS.get(frequency, frequency)

    lines = [
        f"⚠️ Привычка «{title}» ({time_display}, {freq_label}) "
        "конфликтует с существующими привычками:\n",
    ]
    for habit in conflicting:
        c_time = (
            f"{habit.start_time.strftime('%H:%M')}–"
            f"{habit.end_time.strftime('%H:%M')}"
            if habit.end_time
            else f"{habit.start_time.strftime('%H:%M')}, без окончания"
        )
        c_freq = FREQ_LABELS.get(habit.frequency, habit.frequency)
        day_overlap = _freq_day_overlap(frequency, habit.frequency)
        annotation = ""
        if day_overlap and day_overlap != {0, 1, 2, 3, 4, 5, 6}:
            annotation = f" — конфликт {_days_display(day_overlap)}"
        lines.append(f"• {habit.title} ({c_time}, {c_freq}){annotation}")

    lines.append("\nВыберите действие:")
    return "\n".join(lines)


async def _save_habit_from_fsm(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Save a habit using data stored in FSM (for force_add resolution)."""
    data = await state.get_data()
    title = data.get("habit_title", data.get("title", ""))
    start_time = data.get("habit_start_time", data.get("start_time"))
    end_time = data.get("habit_end_time", data.get("end_time"))
    frequency = data.get("habit_frequency", data.get("frequency", "daily"))
    telegram_id = callback.from_user.id

    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            await callback.message.edit_text("⚠️ Пользователь не найден.")
            return

        habit = Habit(
            user_id=user.id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            frequency=frequency,
        )
        session.add(habit)
        await session.commit()
        habit_id = habit.id

    await generate_tasks_for_habit(habit_id)

    freq_label = FREQ_LABELS.get(frequency, frequency)
    time_display = (
        f"{start_time.strftime('%H:%M')} – {end_time.strftime('%H:%M')}"
        if end_time
        else "без ограничения по времени"
    )

    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.answer(
        f"✅ Привычка успешно создана!\n\n"
        f"📝 Название: {title}\n"
        f"⏰ Время: {time_display}\n"
        f"🔄 Периодичность: {freq_label}",
        reply_markup=get_main_menu_keyboard(),
    )


# ===================================================================
# Wizard entry point
# ===================================================================


@router.callback_query(F.data == "new_habit:manual")
async def start_new_habit_manual(callback: CallbackQuery, state: FSMContext) -> None:
    """Start the manual 'New Habit' creation wizard.

    Entry point from the new habit choice menu or AI fallback.
    """
    await callback.answer()
    telegram_id = callback.from_user.id

    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Пожалуйста, используйте /start для регистрации.",
            )
            await state.set_state(MainFSM.main_menu)
            return

    await state.set_state(NewHabitFSM.title)
    await callback.message.edit_text(
        "📝 Введите название привычки (от 1 до 200 символов):",
        reply_markup=get_cancel_input_keyboard(),
    )


@router.message(NewHabitFSM.title)
async def process_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip() if message.text else ""
    if not title or len(title) > 200:
        await message.answer(
            "⚠️ Название должно содержать от 1 до 200 символов. Попробуйте ещё раз:",
            reply_markup=get_cancel_input_keyboard(),
        )
        return
    await state.update_data(title=title)
    await state.set_state(NewHabitFSM.start_time)
    await message.answer(
        "⏰ Выберите время начала привычки:", reply_markup=get_time_selection_keyboard()
    )


@router.callback_query(NewHabitFSM.start_time, F.data.startswith("time:"))
async def process_start_time(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    kind, payload = parse_time_callback(callback.data)

    if kind == "hour":
        hour = int(payload)  # type: ignore[arg-type]
        await state.update_data(**{PENDING_HOUR_KEY: hour})
        await callback.message.edit_text(
            f"⏰ Выберите минуты для {hour:02d}:xx:",
            reply_markup=get_minute_selection_keyboard(hour),
        )
        return

    if kind != "final":
        await callback.message.edit_text(
            "⚠️ Некорректное время.",
            reply_markup=get_time_selection_keyboard(),
        )
        return

    start_time = payload  # type: ignore[assignment]
    await state.update_data(start_time=start_time, **{PENDING_HOUR_KEY: None})
    await state.set_state(NewHabitFSM.end_time)
    await callback.message.edit_text(
        "⏰ Выберите время окончания привычки:",
        reply_markup=get_time_selection_keyboard(
            min_time=start_time, show_null_option=True
        ),
    )


@router.callback_query(NewHabitFSM.end_time, F.data.startswith("time:"))
async def process_end_time(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    start_time: time | None = data.get("start_time")
    kind, payload = parse_time_callback(callback.data)

    if kind == "null":
        await state.update_data(end_time=None, **{PENDING_HOUR_KEY: None})
        await state.set_state(NewHabitFSM.frequency)
        await callback.message.edit_text(
            "🔄 Выберите периодичность привычки:", reply_markup=get_frequency_keyboard()
        )
        return

    if kind == "hour":
        hour = int(payload)  # type: ignore[arg-type]
        await state.update_data(**{PENDING_HOUR_KEY: hour})
        await callback.message.edit_text(
            f"⏰ Выберите минуты для {hour:02d}:xx:",
            reply_markup=get_minute_selection_keyboard(
                hour, min_time=start_time, show_null_option=True
            ),
        )
        return

    if kind != "final":
        await callback.message.edit_text(
            "⚠️ Некорректное время.",
            reply_markup=get_time_selection_keyboard(
                min_time=start_time, show_null_option=True
            ),
        )
        return

    end_time = payload  # type: ignore[assignment]
    if start_time is not None and end_time <= start_time:
        await state.update_data(**{PENDING_HOUR_KEY: None})
        await callback.message.edit_text(
            "⚠️ Время окончания должно быть позже времени начала.",
            reply_markup=get_time_selection_keyboard(
                min_time=start_time, show_null_option=True
            ),
        )
        return
    await state.update_data(end_time=end_time, **{PENDING_HOUR_KEY: None})
    await state.set_state(NewHabitFSM.frequency)
    await callback.message.edit_text(
        "🔄 Выберите периодичность привычки:", reply_markup=get_frequency_keyboard()
    )



@router.callback_query(NewHabitFSM.frequency, F.data.startswith("freq:"))
async def process_frequency(callback: CallbackQuery, state: FSMContext) -> None:
    """Store frequency, check conflicts, save habit."""
    await callback.answer()
    frequency = callback.data.split(":", 1)[1]
    if frequency not in ("daily", "weekdays", "weekends"):
        await callback.message.edit_text("⚠️ Некорректная периодичность.")
        return

    data = await state.get_data()
    title: str = data.get("title", "")
    start_time: time | None = data.get("start_time")
    end_time: time | None = data.get("end_time")
    telegram_id = callback.from_user.id

    if not title or start_time is None:
        await callback.message.edit_text("⚠️ Ошибка. Начните создание привычки заново.")
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        return

    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            await callback.message.edit_text("⚠️ Пользователь не найден.")
            await state.clear()
            await state.set_state(MainFSM.main_menu)
            return

        # --- Conflict detection ---
        conflicting = await check_habit_conflicts(
            session,
            user.id,
            start_time,
            end_time,
            frequency,
        )
        if conflicting:
            await state.update_data(
                habit_title=title,
                habit_start_time=start_time,
                habit_end_time=end_time,
                habit_frequency=frequency,
                habit_user_id=user.id,
                conflict_is_edit=False,
            )
            await state.set_state(ConflictHabitFSM.choose_action)
            await callback.message.edit_text(
                _build_habit_conflict_message(
                    title, start_time, end_time, frequency, conflicting
                ),
                reply_markup=get_habit_conflict_resolution_keyboard(is_edit=False),
            )
            return

        # No conflicts — save
        habit = Habit(
            user_id=user.id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            frequency=frequency,
        )
        session.add(habit)
        await session.commit()
        habit_id = habit.id

    logger.info("process_frequency: generating tasks for habit %d", habit_id)
    await generate_tasks_for_habit(habit_id)

    freq_label = FREQ_LABELS.get(frequency, frequency)
    time_display = (
        f"{start_time.strftime('%H:%M')} – {end_time.strftime('%H:%M')}"
        if end_time
        else "без ограничения по времени"
    )
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.answer(
        f"✅ Привычка успешно создана!\n\n"
        f"📝 Название: {title}\n⏰ Время: {time_display}\n🔄 Периодичность: {freq_label}",
        reply_markup=get_main_menu_keyboard(),
    )


# ===================================================================
# View habit list
# ===================================================================


@router.callback_query(F.data == "main_menu:habits")
async def show_habits(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _show_habit_list(
        telegram_id=callback.from_user.id, target=callback.message, state=state
    )


# ===================================================================
# Two-level habit navigation: interact sub-menu
# ===================================================================


@router.callback_query(F.data == "habits:interact")
async def show_interact_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Show each habit as an inline button in a sub-menu."""
    await callback.answer()
    telegram_id = callback.from_user.id

    async with get_db() as session:
        stmt = (
            select(Habit)
            .join(User)
            .where(User.telegram_id == telegram_id)
            .order_by(Habit.id)
        )
        result = await session.execute(stmt)
        habits = result.scalars().all()

    if not habits:
        await callback.message.edit_text(
            "У вас пока нет привычек.\nСоздайте первую через ➕ Создать привычку!",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        return

    # Preserve the text list from the previous message
    lines = ["📋 Ваши привычки:"]
    for i, habit in enumerate(habits, start=1):
        if habit.end_time is None:
            time_str = f"{habit.start_time.strftime('%H:%M')}, без ограничения"
        else:
            time_str = (
                f"{habit.start_time.strftime('%H:%M')}"
                f"–{habit.end_time.strftime('%H:%M')}"
            )
        freq = FREQ_LABELS.get(habit.frequency, habit.frequency)
        lines.append(f"{i}. {habit.title} ({time_str}, {freq})")

    builder = InlineKeyboardBuilder()
    for habit in habits:
        builder.button(text=habit.title, callback_data=f"habit:select:{habit.id}")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(*(1 for _ in habits), 2)

    await state.set_state(HabitFSM.interact_list)
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=finalize_markup(builder)
    )



async def _show_manage_menu(
    callback: CallbackQuery,
    state: FSMContext,
    habit_id: int,
    habit_title: str,
) -> None:
    """Render the manage menu (edit/delete) for a single habit."""
    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.edit_text("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=callback.from_user.id, target=callback.message, state=state
            )
            return

        if habit.end_time is None:
            time_str = f"{habit.start_time.strftime('%H:%M')}, без ограничения"
        else:
            time_str = (
                f"{habit.start_time.strftime('%H:%M')}"
                f"–{habit.end_time.strftime('%H:%M')}"
            )
        freq = FREQ_LABELS.get(habit.frequency, habit.frequency)

        lines = [
            f"📝 <b>{habit_title}</b>",
            f"⏰ Время: {time_str}",
            f"🔄 Периодичность: {freq}",
            "",
            "Выберите действие:",
        ]

        builder = InlineKeyboardBuilder()
        builder.button(text="✏️ Изменить", callback_data=f"habit:edit:{habit_id}")
        builder.button(text="🗑 Удалить", callback_data=f"habit:delete:{habit_id}")
        builder.button(text="⬅️ Назад", callback_data="nav:back")
        builder.button(text="❌ Отмена", callback_data="nav:cancel")
        builder.adjust(2, 2)

    await state.update_data(manage_habit_id=habit_id, manage_habit_title=habit_title)
    await state.set_state(HabitFSM.manage_single)
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=finalize_markup(builder)
    )



@router.callback_query(F.data.startswith("habit:select:"))
async def show_habit_manage_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the manage menu for a single habit (edit / delete)."""
    await callback.answer()
    habit_id = int(callback.data.split(":")[2])
    telegram_id = callback.from_user.id

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.edit_text("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=telegram_id, target=callback.message, state=state
            )
            return

        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None or habit.user_id != user.id:
            await callback.message.edit_text("⚠️ Эта привычка вам не принадлежит.")
            await _show_habit_list(
                telegram_id=telegram_id, target=callback.message, state=state
            )
            return

    await _show_manage_menu(callback, state, habit_id, habit.title)


# ===================================================================
# Edit flow — start
# ===================================================================


@router.callback_query(F.data.startswith("habit:edit:"))
async def start_edit_habit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    habit_id = int(callback.data.split(":")[2])
    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
    if habit is None:
        await callback.message.edit_text("⚠️ Привычка не найдена.")
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
        return
    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == callback.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
    if user is None or habit.user_id != user.id:
        await callback.message.edit_text("⚠️ Эта привычка вам не принадлежит.")
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
        return

    # Track whether we came from manage_single so back can return there
    current_state = await state.get_state()
    from_manage_single = current_state == HabitFSM.manage_single.state

    await state.update_data(
        edit_habit_id=habit_id,
        edit_habit_title=habit.title,
        from_manage_single=from_manage_single,
    )
    await state.set_state(EditHabitFSM.choose_field)
    await callback.message.edit_text(
        f"Что вы хотите изменить в привычке «{habit.title}»?",
        reply_markup=get_edit_field_keyboard(),
    )


# ===================================================================
# Edit field dispatchers
# ===================================================================


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:title")
async def edit_title_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(EditHabitFSM.title)
    await callback.message.answer(
        "📝 Введите новое название (от 1 до 200 символов):",
        reply_markup=get_cancel_input_keyboard(),
    )


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:start_time")
async def edit_start_time_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(EditHabitFSM.start_time)
    await callback.message.edit_text(
        "🕐 Выберите новое время начала:", reply_markup=get_time_selection_keyboard()
    )


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:end_time")
async def edit_end_time_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]
    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
    if habit is None:
        await callback.message.edit_text("⚠️ Привычка не найдена.")
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
        return
    await state.set_state(EditHabitFSM.end_time)
    await callback.message.edit_text(
        "🕐 Выберите новое время окончания:",
        reply_markup=get_time_selection_keyboard(
            min_time=habit.start_time, show_null_option=True
        ),
    )


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:frequency")
async def edit_frequency_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(EditHabitFSM.frequency)
    await callback.message.edit_text(
        "📅 Выберите новую частоту:", reply_markup=get_frequency_keyboard()
    )


# ===================================================================
# Apply title change
# ===================================================================


@router.message(EditHabitFSM.title)
async def apply_title_edit(message: Message, state: FSMContext) -> None:
    title = message.text.strip() if message.text else ""
    if not title or len(title) > 200:
        await message.answer(
            "⚠️ Название должно содержать от 1 до 200 символов. Попробуйте ещё раз:",
            reply_markup=get_cancel_input_keyboard(),
        )
        return
    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]
    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await message.answer("⚠️ Привычка не найдена.")
        else:
            habit.title = title
            await session.commit()
            await message.answer(f"✅ Название изменено на «{title}».")
    async with get_db() as session:
        await session.execute(delete(Task).where(Task.habit_id == habit_id))
        await session.commit()
        await generate_tasks_for_habit(habit_id)
    await _show_habit_list(
        telegram_id=message.from_user.id, target=message, state=state
    )


# ===================================================================
# Apply start time — with conflict check
# ===================================================================


@router.callback_query(
    EditHabitFSM.start_time, F.data.startswith("time:"), F.data != "time:null"
)
async def apply_start_time_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    kind, payload = parse_time_callback(callback.data)

    if kind == "hour":
        hour = int(payload)  # type: ignore[arg-type]
        await state.update_data(**{PENDING_HOUR_KEY: hour})
        await callback.message.edit_text(
            f"🕐 Выберите минуты для {hour:02d}:xx:",
            reply_markup=get_minute_selection_keyboard(hour),
        )
        return

    if kind != "final":
        await callback.message.edit_text(
            "⚠️ Некорректное время.",
            reply_markup=get_time_selection_keyboard(),
        )
        return

    new_start_time = payload  # type: ignore[assignment]
    await state.update_data(**{PENDING_HOUR_KEY: None})
    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.edit_text("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=callback.from_user.id, target=callback.message, state=state
            )
            return
        if habit.end_time is not None and new_start_time >= habit.end_time:
            await callback.message.edit_text(
                "⚠️ Время начала должно быть раньше времени окончания.",
                reply_markup=get_time_selection_keyboard(),
            )
            return

        conflicting = await check_habit_conflicts(
            session,
            habit.user_id,
            new_start_time,
            habit.end_time,
            habit.frequency,
            exclude_habit_id=habit_id,
        )
        if conflicting:
            await state.update_data(conflict_is_edit=True, edit_habit_id=habit_id)
            await state.set_state(ConflictHabitFSM.choose_action)
            await callback.message.edit_text(
                _build_habit_conflict_message(
                    habit.title,
                    new_start_time,
                    habit.end_time,
                    habit.frequency,
                    conflicting,
                ),
                reply_markup=get_habit_conflict_resolution_keyboard(is_edit=True),
            )
            return

        habit.start_time = new_start_time
        await session.commit()
        await callback.message.answer(
            f"✅ Время начала изменено на {new_start_time.strftime('%H:%M')}."
        )

    async with get_db() as session:
        await session.execute(delete(Task).where(Task.habit_id == habit_id))
        await session.commit()
        await generate_tasks_for_habit(habit_id)
    await _show_habit_list(
        telegram_id=callback.from_user.id, target=callback.message, state=state
    )



# ===================================================================
# Apply end time — with conflict check
# ===================================================================


@router.callback_query(EditHabitFSM.end_time, F.data.startswith("time:"))
async def apply_end_time_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]
    kind, payload = parse_time_callback(callback.data)

    # Load habit early for min_time / validation
    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.edit_text("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=callback.from_user.id, target=callback.message, state=state
            )
            return
        habit_start = habit.start_time
        habit_user_id = habit.user_id
        habit_title = habit.title
        habit_frequency = habit.frequency

    if kind == "null":
        new_end_time: time | None = None
    elif kind == "hour":
        hour = int(payload)  # type: ignore[arg-type]
        await state.update_data(**{PENDING_HOUR_KEY: hour})
        await callback.message.edit_text(
            f"🕐 Выберите минуты для {hour:02d}:xx:",
            reply_markup=get_minute_selection_keyboard(
                hour, min_time=habit_start, show_null_option=True
            ),
        )
        return
    elif kind == "final":
        new_end_time = payload  # type: ignore[assignment]
        if new_end_time <= habit_start:
            await state.update_data(**{PENDING_HOUR_KEY: None})
            await callback.message.edit_text(
                "⚠️ Время окончания должно быть позже времени начала.",
                reply_markup=get_time_selection_keyboard(
                    min_time=habit_start, show_null_option=True
                ),
            )
            return
    else:
        await callback.message.edit_text(
            "⚠️ Некорректное время.",
            reply_markup=get_time_selection_keyboard(
                min_time=habit_start, show_null_option=True
            ),
        )
        return

    await state.update_data(**{PENDING_HOUR_KEY: None})

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.edit_text("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=callback.from_user.id, target=callback.message, state=state
            )
            return

        conflicting = await check_habit_conflicts(
            session,
            habit_user_id,
            habit_start,
            new_end_time,
            habit_frequency,
            exclude_habit_id=habit_id,
        )
        if conflicting:
            await state.update_data(conflict_is_edit=True, edit_habit_id=habit_id)
            await state.set_state(ConflictHabitFSM.choose_action)
            await callback.message.edit_text(
                _build_habit_conflict_message(
                    habit_title,
                    habit_start,
                    new_end_time,
                    habit_frequency,
                    conflicting,
                ),
                reply_markup=get_habit_conflict_resolution_keyboard(is_edit=True),
            )
            return

        habit.end_time = new_end_time
        await session.commit()
        if new_end_time is None:
            await callback.message.answer(
                "✅ Время окончания сброшено (без ограничения)."
            )
        else:
            await callback.message.answer(
                f"✅ Время окончания изменено на {new_end_time.strftime('%H:%M')}."
            )

    async with get_db() as session:
        await session.execute(delete(Task).where(Task.habit_id == habit_id))
        await session.commit()
        await generate_tasks_for_habit(habit_id)
    await _show_habit_list(
        telegram_id=callback.from_user.id, target=callback.message, state=state
    )



# ===================================================================
# Apply frequency — with conflict check
# ===================================================================


@router.callback_query(EditHabitFSM.frequency, F.data.startswith("freq:"))
async def apply_frequency_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    frequency = callback.data.split(":", 1)[1]
    if frequency not in ("daily", "weekdays", "weekends"):
        await callback.message.edit_text("⚠️ Некорректная периодичность.")
        return

    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.edit_text("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=callback.from_user.id, target=callback.message, state=state
            )
            return

        conflicting = await check_habit_conflicts(
            session,
            habit.user_id,
            habit.start_time,
            habit.end_time,
            frequency,
            exclude_habit_id=habit_id,
        )
        if conflicting:
            await state.update_data(conflict_is_edit=True, edit_habit_id=habit_id)
            await state.set_state(ConflictHabitFSM.choose_action)
            await callback.message.edit_text(
                _build_habit_conflict_message(
                    habit.title,
                    habit.start_time,
                    habit.end_time,
                    frequency,
                    conflicting,
                ),
                reply_markup=get_habit_conflict_resolution_keyboard(is_edit=True),
            )
            return

        habit.frequency = frequency
        await session.commit()
        await callback.message.answer(
            f"✅ Частота изменена на «{FREQ_LABELS.get(frequency, frequency)}»."
        )

    async with get_db() as session:
        await session.execute(delete(Task).where(Task.habit_id == habit_id))
        await session.commit()
        await generate_tasks_for_habit(habit_id)
    await _show_habit_list(
        telegram_id=callback.from_user.id, target=callback.message, state=state
    )


# ===================================================================
# Conflict resolution handlers
# ===================================================================


@router.callback_query(
    ConflictHabitFSM.choose_action, F.data == "conflict_habit:force_add"
)
async def conflict_habit_force_add(callback: CallbackQuery, state: FSMContext) -> None:
    """Save habit despite conflicts."""
    await callback.answer()
    data = await state.get_data()
    is_edit = data.get("conflict_is_edit", False)

    if is_edit:
        # Apply pending edit changes
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
        await callback.message.answer(
            "✅ Изменения сохранены (конфликт проигнорирован)."
        )
    else:
        await _save_habit_from_fsm(callback, state)


@router.callback_query(
    ConflictHabitFSM.choose_action, F.data == "conflict_habit:change_time"
)
async def conflict_habit_change_time(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Return to start time selection step (allows editing both start and end time)."""
    await callback.answer()
    data = await state.get_data()
    is_edit = data.get("conflict_is_edit", False)
    if is_edit:
        await state.set_state(EditHabitFSM.start_time)
        await callback.message.edit_text(
            "🕐 Выберите новое время начала:",
            reply_markup=get_time_selection_keyboard(),
        )
    else:
        await state.set_state(NewHabitFSM.start_time)
        await callback.message.edit_text(
            "⏰ Выберите время начала привычки:",
            reply_markup=get_time_selection_keyboard(),
        )


@router.callback_query(
    ConflictHabitFSM.choose_action, F.data == "conflict_habit:change_frequency"
)
async def conflict_habit_change_frequency(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Return to frequency selection step."""
    await callback.answer()
    data = await state.get_data()
    is_edit = data.get("conflict_is_edit", False)
    if is_edit:
        await state.set_state(EditHabitFSM.frequency)
    else:
        await state.set_state(NewHabitFSM.frequency)
    await callback.message.edit_text(
        "📅 Выберите частоту:", reply_markup=get_frequency_keyboard()
    )


@router.callback_query(
    ConflictHabitFSM.choose_action, F.data == "conflict_habit:edit_schedule"
)
async def conflict_habit_edit_schedule(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Stub for Edit Schedule feature."""
    await callback.answer()
    await state.set_state(ConflictHabitFSM.choose_action)
    await callback.message.edit_text(
        "Функция будет доступна в следующей версии.",
        reply_markup=get_habit_conflict_resolution_keyboard(is_edit=True),
    )


@router.callback_query(
    ConflictHabitFSM.choose_action, F.data == "conflict_habit:edit_tasks"
)
async def conflict_habit_edit_tasks(callback: CallbackQuery, state: FSMContext) -> None:
    """Stub for Edit Conflicting Tasks feature."""
    await callback.answer()
    await state.set_state(ConflictHabitFSM.choose_action)
    await callback.message.edit_text(
        "Функция будет доступна в следующей версии.",
        reply_markup=get_habit_conflict_resolution_keyboard(is_edit=True),
    )


# ===================================================================
# Delete flow
# ===================================================================


@router.callback_query(F.data.startswith("habit:delete:"))
async def confirm_delete_habit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    habit_id = int(callback.data.split(":")[2])
    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
    if habit is None:
        await callback.message.edit_text("⚠️ Привычка не найдена.")
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
        return
    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == callback.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
    if user is None or habit.user_id != user.id:
        await callback.message.edit_text("⚠️ Эта привычка вам не принадлежит.")
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
        return
    await state.update_data(edit_habit_id=habit_id, edit_habit_title=habit.title)
    await state.set_state(EditHabitFSM.confirm_delete)
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить привычку «{habit.title}»?\nВсе связанные данные будут удалены.",
        reply_markup=get_delete_confirmation_keyboard(habit_id),
    )


@router.callback_query(
    EditHabitFSM.confirm_delete, F.data.startswith("habit:confirm_delete:")
)
async def execute_delete_habit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    habit_id = int(callback.data.split(":")[2])
    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is not None:
            await session.delete(habit)
            await session.commit()
            await callback.message.answer("🗑 Привычка удалена.")
        else:
            await callback.message.answer("⚠️ Привычка не найдена.")
    await _show_habit_list(
        telegram_id=callback.from_user.id, target=callback.message, state=state
    )


# ===================================================================
# Navigation — Back button
# ===================================================================


@router.callback_query(F.data == "nav:back")
async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    current_state = await state.get_state()
    fsm_data = await state.get_data()

    # --- Two-step time picker: back from minutes → hours ---
    pending_hour = fsm_data.get(PENDING_HOUR_KEY)
    if pending_hour is not None and current_state in (
        NewHabitFSM.start_time.state,
        NewHabitFSM.end_time.state,
        EditHabitFSM.start_time.state,
        EditHabitFSM.end_time.state,
    ):
        await state.update_data(**{PENDING_HOUR_KEY: None})
        min_time = None
        show_null = False
        prompt = "⏰ Выберите время:"
        if current_state == NewHabitFSM.start_time.state:
            prompt = "⏰ Выберите время начала привычки:"
        elif current_state == NewHabitFSM.end_time.state:
            prompt = "⏰ Выберите время окончания привычки:"
            min_time = fsm_data.get("start_time")
            show_null = True
        elif current_state == EditHabitFSM.start_time.state:
            prompt = "🕐 Выберите новое время начала:"
        elif current_state == EditHabitFSM.end_time.state:
            prompt = "🕐 Выберите новое время окончания:"
            show_null = True
            habit_id = fsm_data.get("edit_habit_id")
            if habit_id is not None:
                async with get_db() as session:
                    habit = await session.get(Habit, habit_id)
                    if habit is not None:
                        min_time = habit.start_time
        await callback.message.edit_text(
            prompt,
            reply_markup=get_time_selection_keyboard(
                min_time=min_time, show_null_option=show_null
            ),
        )
        return

    # --- ConflictHabitFSM ---
    if current_state == ConflictHabitFSM.choose_action.state:

        data = await state.get_data()
        is_edit = data.get("conflict_is_edit", False)
        if is_edit:
            await state.set_state(EditHabitFSM.choose_field)
            title = data.get("edit_habit_title", "этой привычки")
            await callback.message.edit_text(
                f"Что вы хотите изменить в привычке «{title}»?",
                reply_markup=get_edit_field_keyboard(),
            )
        else:
            await state.set_state(NewHabitFSM.frequency)
            await callback.message.edit_text(
                "🔄 Выберите периодичность привычки:",
                reply_markup=get_frequency_keyboard(),
            )
        return

    # --- NewHabitFSM ---
    if current_state == NewHabitFSM.start_time.state:
        await state.set_state(NewHabitFSM.title)
        await callback.message.answer(
            "📝 Введите название привычки (от 1 до 200 символов):"
        )
        return
    if current_state == NewHabitFSM.end_time.state:
        await state.update_data(**{PENDING_HOUR_KEY: None})
        await state.set_state(NewHabitFSM.start_time)
        await callback.message.edit_text(
            "⏰ Выберите время начала привычки:",
            reply_markup=get_time_selection_keyboard(),
        )
        return
    if current_state == NewHabitFSM.frequency.state:
        await state.update_data(**{PENDING_HOUR_KEY: None})
        await state.set_state(NewHabitFSM.end_time)
        st = fsm_data.get("start_time")
        await callback.message.edit_text(
            "⏰ Выберите время окончания привычки:",
            reply_markup=get_time_selection_keyboard(
                min_time=st, show_null_option=True
            ),
        )
        return


    # --- HabitFSM ---
    if current_state == HabitFSM.interact_list.state:
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
        return
    if current_state == HabitFSM.manage_single.state:
        # Return to interact_list sub-menu
        await show_interact_menu(callback, state)
        return

    # --- EditHabitFSM ---
    if current_state in (
        EditHabitFSM.title.state,
        EditHabitFSM.start_time.state,
        EditHabitFSM.end_time.state,
        EditHabitFSM.frequency.state,
    ):
        title = fsm_data.get("edit_habit_title", "этой привычки")
        await state.update_data(**{PENDING_HOUR_KEY: None})
        await state.set_state(EditHabitFSM.choose_field)
        await callback.message.edit_text(
            f"Что вы хотите изменить в привычке «{title}»?",
            reply_markup=get_edit_field_keyboard(),
        )
        return
    if current_state == EditHabitFSM.choose_field.state:
        from_manage_single = fsm_data.get("from_manage_single", False)

        if from_manage_single:
            # Return to the manage_single menu
            habit_id = fsm_data.get("edit_habit_id")
            habit_title = fsm_data.get("edit_habit_title", "этой привычки")
            await state.update_data(
                manage_habit_id=habit_id, manage_habit_title=habit_title
            )
            await state.set_state(HabitFSM.manage_single)
            await _show_manage_menu(callback, state, habit_id, habit_title)
        else:
            await _show_habit_list(
                telegram_id=callback.from_user.id, target=callback.message, state=state
            )
        return

    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )


# ===================================================================
# Navigation — Cancel button (only for habit-related states)
# ===================================================================


@router.callback_query(
    F.data == "nav:cancel",
    StateFilter(*_HABIT_CANCEL_STATES),
)
async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    current_state = await state.get_state()

    # HabitFSM states: just go to main menu silently
    is_habit_nav = current_state in (
        HabitFSM.view_list.state,
        HabitFSM.interact_list.state,
        HabitFSM.manage_single.state,
    )
    if is_habit_nav:
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            "🏠 Главное меню бота\nВыберите действие:",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    # Distinguish editing habits from creating new ones
    is_edit = current_state is not None and current_state.startswith("EditHabitFSM:")
    if not is_edit and current_state == ConflictHabitFSM.choose_action.state:
        data = await state.get_data()
        is_edit = data.get("conflict_is_edit", False)

    await state.clear()
    await state.set_state(MainFSM.main_menu)
    if is_edit:
        await callback.message.edit_text("❌ Редактирование отменено.")
        await _show_habit_list(
            telegram_id=callback.from_user.id, target=callback.message, state=state
        )
    else:
        await callback.message.edit_text(
            "❌ Создание привычки отменено.", reply_markup=get_main_menu_keyboard()
        )
