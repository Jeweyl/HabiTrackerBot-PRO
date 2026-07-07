"""Handlers for habit creation, listing, editing, and deletion."""

import logging
from datetime import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from src.db.models import Habit, User
from src.db.session import get_db
from src.keyboards.inline import (
    get_delete_confirmation_keyboard,
    get_edit_field_keyboard,
    get_frequency_keyboard,
    get_main_menu_keyboard,
    get_time_selection_keyboard,
)
from src.states.fsm import EditHabitFSM, MainFSM, NewHabitFSM

logger = logging.getLogger(__name__)

router = Router()
"""Router for habit-related handlers (new habit wizard, listing, edit, delete)."""

# ---------------------------------------------------------------------------
# Helper: show the habit list
# ---------------------------------------------------------------------------

FREQ_LABELS: dict[str, str] = {
    "daily": "📅 Ежедневно",
    "weekdays": "📆 По будням",
    "weekends": "🎉 По выходным",
}
"""Mapping from frequency slug to display label."""


async def _show_habit_list(
    *,
    telegram_id: int,
    target: Message,
    state: FSMContext,
) -> None:
    """Fetch and display the user's habit list with edit/delete buttons.

    Clears FSM state and returns to ``MainFSM.main_menu``.  If the user
    has no habits, a placeholder message with the main menu is shown.

    .. note:: For MVP the full list is shown at once.  Pagination should be
       considered when the number of habits grows beyond ~10.

    Args:
        telegram_id: Telegram ID of the user whose habits to show.
        target: The message to edit/reply to with the habit list.
        state: FSM context for the current user.
    """
    await state.clear()
    await state.set_state(MainFSM.main_menu)

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
        await target.answer(
            "У вас пока нет привычек. Создайте первую через ➕ Новая привычка!",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    lines = ["📋 Ваши привычки:"]
    builder = InlineKeyboardBuilder()
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
        builder.button(
            text="✏️ Изменить",
            callback_data=f"habit:edit:{habit.id}",
        )
        builder.button(
            text="🗑 Удалить",
            callback_data=f"habit:delete:{habit.id}",
        )

    builder.adjust(*([2] * len(habits)))  # edit + delete per habit, 2 per row
    lines.append("\nВыберите привычку для управления:")
    await target.answer("\n".join(lines), reply_markup=builder.as_markup())


# ---------------------------------------------------------------------------
# Wizard entry point — triggered by the "➕ Новая привычка" main menu button
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "main_menu:new_habit")
async def start_new_habit(callback: CallbackQuery, state: FSMContext) -> None:
    """Start the "New Habit" creation wizard.

    Verifies the user exists in the database, then transitions to the
    ``NewHabitFSM.title`` state and prompts for a habit name.

    Args:
        callback: Incoming callback query from the main menu button.
        state: FSM context for the current user.
    """
    await callback.answer()

    telegram_id = callback.from_user.id

    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            await callback.message.answer(
                "⚠️ Пользователь не найден. Пожалуйста, используйте /start для регистрации.",
            )
            await state.set_state(MainFSM.main_menu)
            return

    await state.set_state(NewHabitFSM.title)
    await callback.message.answer(
        "📝 Введите название привычки (от 1 до 200 символов):",
    )


# ---------------------------------------------------------------------------
# Step 1 — process the habit title
# ---------------------------------------------------------------------------


@router.message(NewHabitFSM.title)
async def process_title(message: Message, state: FSMContext) -> None:
    """Receive and validate the habit title.

    Strips whitespace and checks that the title is between 1 and 200
    characters.  On success, stores the title in FSM data and moves to
    the ``NewHabitFSM.start_time`` state.

    Args:
        message: Incoming text message with the habit title.
        state: FSM context for the current user.
    """
    title = message.text.strip() if message.text else ""

    if not title or len(title) > 200:
        await message.answer(
            "⚠️ Название должно содержать от 1 до 200 символов. Попробуйте ещё раз:",
        )
        return

    await state.update_data(title=title)
    await state.set_state(NewHabitFSM.start_time)

    await message.answer(
        "⏰ Выберите время начала привычки:",
        reply_markup=get_time_selection_keyboard(),
    )


# ---------------------------------------------------------------------------
# Step 2 — process the start time
# ---------------------------------------------------------------------------


@router.callback_query(NewHabitFSM.start_time, F.data.startswith("time:"))
async def process_start_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Store the selected start time and move to the end-time step.

    Parses the ``HH:MM`` string from the callback data, stores it in FSM
    data, and transitions to ``NewHabitFSM.end_time``.

    Args:
        callback: Incoming callback query from the time keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    time_str = callback.data.split(":", 1)[1]  # "time:09:00" → "09:00"
    try:
        hour, minute = map(int, time_str.split(":"))
        start_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.answer(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    await state.update_data(start_time=start_time)
    await state.set_state(NewHabitFSM.end_time)

    await callback.message.answer(
        "⏰ Выберите время окончания привычки:",
        reply_markup=get_time_selection_keyboard(
            min_time=start_time, show_null_option=True
        ),
    )


# ---------------------------------------------------------------------------
# Step 3 — process the end time
# ---------------------------------------------------------------------------


@router.callback_query(NewHabitFSM.end_time, F.data.startswith("time:"))
async def process_end_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Store the selected end time and move to the frequency step.

    Parses the ``HH:MM`` string from the callback data.  Supports the
    special ``time:null`` callback to skip the end time (stores ``None``).
    Validates that the chosen time is strictly after *start_time*.

    Args:
        callback: Incoming callback query from the time keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    data = await state.get_data()
    start_time: time | None = data.get("start_time")

    # Special case: "Без времени" button
    if callback.data == "time:null":
        await state.update_data(end_time=None)
        await state.set_state(NewHabitFSM.frequency)
        await callback.message.answer(
            "🔄 Выберите периодичность привычки:",
            reply_markup=get_frequency_keyboard(),
        )
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

    await state.update_data(end_time=end_time)
    await state.set_state(NewHabitFSM.frequency)

    await callback.message.answer(
        "🔄 Выберите периодичность привычки:",
        reply_markup=get_frequency_keyboard(),
    )


# ---------------------------------------------------------------------------
# Step 4 — process the frequency and save the habit
# ---------------------------------------------------------------------------


@router.callback_query(NewHabitFSM.frequency, F.data.startswith("freq:"))
async def process_frequency(callback: CallbackQuery, state: FSMContext) -> None:
    """Store the frequency, persist the habit, and show a confirmation.

    Reads all accumulated data from FSM, creates a ``Habit`` record in the
    database, sends a confirmation message, clears the FSM state, and
    returns the user to the main menu.

    Args:
        callback: Incoming callback query from the frequency keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    frequency = callback.data.split(":", 1)[1]  # "freq:daily" → "daily"
    if frequency not in ("daily", "weekdays", "weekends"):
        await callback.message.answer(
            "⚠️ Некорректная периодичность. Пожалуйста, выберите из списка.",
        )
        return

    data = await state.get_data()
    title: str = data.get("title", "")
    start_time: time | None = data.get("start_time")
    end_time: time | None = data.get("end_time")
    telegram_id = callback.from_user.id

    if not title or start_time is None:
        await callback.message.answer(
            "⚠️ Произошла ошибка. Пожалуйста, начните создание привычки заново.",
        )
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        return

    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            await callback.message.answer(
                "⚠️ Пользователь не найден. Пожалуйста, используйте /start.",
            )
            await state.clear()
            await state.set_state(MainFSM.main_menu)
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

    freq_label = FREQ_LABELS.get(frequency, frequency)

    await state.clear()
    await state.set_state(MainFSM.main_menu)

    if end_time is None:
        time_display = "без ограничения по времени"
    else:
        time_display = f"{start_time.strftime('%H:%M')} – {end_time.strftime('%H:%M')}"

    await callback.message.answer(
        f"✅ Привычка успешно создана!\n\n"
        f"📝 Название: {title}\n"
        f"⏰ Время: {time_display}\n"
        f"🔄 Периодичность: {freq_label}",
        reply_markup=get_main_menu_keyboard(),
    )


# ---------------------------------------------------------------------------
# View habit list — triggered by the "📋 Мои привычки" main menu button
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "main_menu:habits")
async def show_habits(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the user's habit list with edit and delete controls.

    Args:
        callback: Incoming callback query from the main menu button.
        state: FSM context for the current user.
    """
    await callback.answer()
    await _show_habit_list(
        telegram_id=callback.from_user.id,
        target=callback.message,
        state=state,
    )


# ===================================================================
# Edit flow
# ===================================================================


# ---------------------------------------------------------------------------
# Start editing — triggered by "✏️ Изменить" button
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("habit:edit:"))
async def start_edit_habit(callback: CallbackQuery, state: FSMContext) -> None:
    """Enter the edit mode for a specific habit.

    Loads the habit from the database, verifies ownership, saves the
    habit ID in FSM data, transitions to ``EditHabitFSM.choose_field``,
    and prompts the user to select which field to modify.

    Args:
        callback: Incoming callback query from the habit list.
        state: FSM context for the current user.
    """
    await callback.answer()
    habit_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)

    if habit is None:
        await callback.message.answer("⚠️ Привычка не найдена.")
        await _show_habit_list(
            telegram_id=callback.from_user.id,
            target=callback.message,
            state=state,
        )
        return

    # Security: verify the habit belongs to the current user
    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == callback.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

    if user is None or habit.user_id != user.id:
        await callback.message.answer("⚠️ Эта привычка вам не принадлежит.")
        await _show_habit_list(
            telegram_id=callback.from_user.id,
            target=callback.message,
            state=state,
        )
        return

    await state.update_data(edit_habit_id=habit_id, edit_habit_title=habit.title)
    await state.set_state(EditHabitFSM.choose_field)
    await callback.message.answer(
        f"Что вы хотите изменить в привычке «{habit.title}»?",
        reply_markup=get_edit_field_keyboard(),
    )


# ---------------------------------------------------------------------------
# Edit field dispatchers — each routes to the appropriate EditHabitFSM state
# ---------------------------------------------------------------------------


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:title")
async def edit_title_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt the user to enter a new title.

    Args:
        callback: Incoming callback query from the edit field keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.set_state(EditHabitFSM.title)
    await callback.message.answer("📝 Введите новое название (от 1 до 200 символов):")


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:start_time")
async def edit_start_time_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt the user to select a new start time.

    Args:
        callback: Incoming callback query from the edit field keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.set_state(EditHabitFSM.start_time)
    await callback.message.answer(
        "🕐 Выберите новое время начала:",
        reply_markup=get_time_selection_keyboard(),
    )


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:end_time")
async def edit_end_time_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt the user to select a new end time.

    Loads the current start_time from the database to pass *min_time* to
    the keyboard, and enables the ``time:null`` option via *show_null_option*.

    Args:
        callback: Incoming callback query from the edit field keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)

    if habit is None:
        await callback.message.answer("⚠️ Привычка не найдена.")
        await _show_habit_list(
            telegram_id=callback.from_user.id,
            target=callback.message,
            state=state,
        )
        return

    await state.set_state(EditHabitFSM.end_time)
    await callback.message.answer(
        "🕐 Выберите новое время окончания:",
        reply_markup=get_time_selection_keyboard(
            min_time=habit.start_time, show_null_option=True
        ),
    )


@router.callback_query(EditHabitFSM.choose_field, F.data == "edit_field:frequency")
async def edit_frequency_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt the user to select a new frequency.

    Args:
        callback: Incoming callback query from the edit field keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.set_state(EditHabitFSM.frequency)
    await callback.message.answer(
        "📅 Выберите новую частоту:",
        reply_markup=get_frequency_keyboard(),
    )


# ---------------------------------------------------------------------------
# Apply title change
# ---------------------------------------------------------------------------


@router.message(EditHabitFSM.title)
async def apply_title_edit(message: Message, state: FSMContext) -> None:
    """Apply a new title to the habit being edited.

    Args:
        message: Incoming text message with the new title.
        state: FSM context for the current user.
    """
    title = message.text.strip() if message.text else ""

    if not title or len(title) > 200:
        await message.answer(
            "⚠️ Название должно содержать от 1 до 200 символов. Попробуйте ещё раз:",
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

    await _show_habit_list(
        telegram_id=message.from_user.id,
        target=message,
        state=state,
    )


# ---------------------------------------------------------------------------
# Apply start time change
# ---------------------------------------------------------------------------


@router.callback_query(
    EditHabitFSM.start_time, F.data.startswith("time:"), F.data != "time:null"
)
async def apply_start_time_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Apply a new start time to the habit being edited.

    Validates that the new start time is before the current end time
    (if one is set).

    Args:
        callback: Incoming callback query from the time keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    time_str = callback.data.split(":", 1)[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        new_start_time = time(hour, minute)
    except (ValueError, IndexError):
        await callback.message.answer(
            "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
        )
        return

    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.answer("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=callback.from_user.id,
                target=callback.message,
                state=state,
            )
            return

        # Validate: new start_time must be < end_time (if end_time exists)
        if habit.end_time is not None and new_start_time >= habit.end_time:
            await callback.message.answer(
                "⚠️ Время начала должно быть раньше времени окончания. "
                "Выберите другое время:",
                reply_markup=get_time_selection_keyboard(),
            )
            return

        habit.start_time = new_start_time
        await session.commit()
        await callback.message.answer(
            f"✅ Время начала изменено на {new_start_time.strftime('%H:%M')}."
        )

    await _show_habit_list(
        telegram_id=callback.from_user.id,
        target=callback.message,
        state=state,
    )


# ---------------------------------------------------------------------------
# Apply end time change
# ---------------------------------------------------------------------------


@router.callback_query(EditHabitFSM.end_time, F.data.startswith("time:"))
async def apply_end_time_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Apply a new end time (or ``None``) to the habit being edited.

    Validates that the new end time (if provided) is after start_time.

    Args:
        callback: Incoming callback query from the time keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.answer("⚠️ Привычка не найдена.")
            await _show_habit_list(
                telegram_id=callback.from_user.id,
                target=callback.message,
                state=state,
            )
            return

        # Special case: "Без времени"
        if callback.data == "time:null":
            habit.end_time = None
            await session.commit()
            await callback.message.answer(
                "✅ Время окончания сброшено (без ограничения)."
            )
        else:
            time_str = callback.data.split(":", 1)[1]
            try:
                hour, minute = map(int, time_str.split(":"))
                new_end_time = time(hour, minute)
            except (ValueError, IndexError):
                await callback.message.answer(
                    "⚠️ Некорректное время. Пожалуйста, выберите время из списка.",
                )
                return

            if new_end_time <= habit.start_time:
                await callback.message.answer(
                    "⚠️ Время окончания должно быть позже времени начала. "
                    "Выберите другое время:",
                    reply_markup=get_time_selection_keyboard(
                        min_time=habit.start_time, show_null_option=True
                    ),
                )
                return

            habit.end_time = new_end_time
            await session.commit()
            await callback.message.answer(
                f"✅ Время окончания изменено на {new_end_time.strftime('%H:%M')}."
            )

    await _show_habit_list(
        telegram_id=callback.from_user.id,
        target=callback.message,
        state=state,
    )


# ---------------------------------------------------------------------------
# Apply frequency change
# ---------------------------------------------------------------------------


@router.callback_query(EditHabitFSM.frequency, F.data.startswith("freq:"))
async def apply_frequency_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Apply a new frequency to the habit being edited.

    Args:
        callback: Incoming callback query from the frequency keyboard.
        state: FSM context for the current user.
    """
    await callback.answer()

    frequency = callback.data.split(":", 1)[1]
    if frequency not in ("daily", "weekdays", "weekends"):
        await callback.message.answer(
            "⚠️ Некорректная периодичность. Пожалуйста, выберите из списка.",
        )
        return

    fsm_data = await state.get_data()
    habit_id: int = fsm_data["edit_habit_id"]

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)
        if habit is None:
            await callback.message.answer("⚠️ Привычка не найдена.")
        else:
            habit.frequency = frequency
            await session.commit()
            freq_label = FREQ_LABELS.get(frequency, frequency)
            await callback.message.answer(f"✅ Частота изменена на «{freq_label}».")

    await _show_habit_list(
        telegram_id=callback.from_user.id,
        target=callback.message,
        state=state,
    )


# ===================================================================
# Delete flow
# ===================================================================


@router.callback_query(F.data.startswith("habit:delete:"))
async def confirm_delete_habit(callback: CallbackQuery, state: FSMContext) -> None:
    """Show a confirmation prompt before deleting a habit.

    Loads the habit, verifies ownership, and shows a confirmation
    keyboard.

    Args:
        callback: Incoming callback query from the habit list.
        state: FSM context for the current user.
    """
    await callback.answer()
    habit_id = int(callback.data.split(":")[2])

    async with get_db() as session:
        habit = await session.get(Habit, habit_id)

    if habit is None:
        await callback.message.answer("⚠️ Привычка не найдена.")
        await _show_habit_list(
            telegram_id=callback.from_user.id,
            target=callback.message,
            state=state,
        )
        return

    # Security: verify ownership
    async with get_db() as session:
        stmt = select(User).where(User.telegram_id == callback.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

    if user is None or habit.user_id != user.id:
        await callback.message.answer("⚠️ Эта привычка вам не принадлежит.")
        await _show_habit_list(
            telegram_id=callback.from_user.id,
            target=callback.message,
            state=state,
        )
        return

    await state.update_data(edit_habit_id=habit_id, edit_habit_title=habit.title)
    await state.set_state(EditHabitFSM.confirm_delete)
    await callback.message.answer(
        f"Вы уверены, что хотите удалить привычку «{habit.title}»?\n"
        "Все связанные данные будут удалены.",
        reply_markup=get_delete_confirmation_keyboard(habit_id),
    )


@router.callback_query(
    EditHabitFSM.confirm_delete, F.data.startswith("habit:confirm_delete:")
)
async def execute_delete_habit(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete a habit after user confirmation.

    Args:
        callback: Incoming callback query from the confirmation keyboard.
        state: FSM context for the current user.
    """
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
        telegram_id=callback.from_user.id,
        target=callback.message,
        state=state,
    )


# ===================================================================
# Navigation — Back button (extended for EditHabitFSM)
# ===================================================================


@router.callback_query(F.data == "nav:back")
async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate one step back in the wizard or edit flow.

    Determines the current FSM state and moves to the previous step,
    re-prompting the user with the appropriate message and keyboard.

    Args:
        callback: Incoming callback query from the back button.
        state: FSM context for the current user.
    """
    await callback.answer()

    current_state = await state.get_state()

    # --- NewHabitFSM back navigation ---
    if current_state == NewHabitFSM.start_time.state:
        await state.set_state(NewHabitFSM.title)
        await callback.message.answer(
            "📝 Введите название привычки (от 1 до 200 символов):",
        )
        return

    if current_state == NewHabitFSM.end_time.state:
        await state.set_state(NewHabitFSM.start_time)
        await callback.message.answer(
            "⏰ Выберите время начала привычки:",
            reply_markup=get_time_selection_keyboard(),
        )
        return

    if current_state == NewHabitFSM.frequency.state:
        await state.set_state(NewHabitFSM.end_time)
        fsm_data = await state.get_data()
        st = fsm_data.get("start_time")
        await callback.message.answer(
            "⏰ Выберите время окончания привычки:",
            reply_markup=get_time_selection_keyboard(
                min_time=st, show_null_option=True
            ),
        )
        return

    # --- EditHabitFSM back navigation ---
    if current_state in (
        EditHabitFSM.title.state,
        EditHabitFSM.start_time.state,
        EditHabitFSM.end_time.state,
        EditHabitFSM.frequency.state,
    ):
        fsm_data = await state.get_data()
        title = fsm_data.get("edit_habit_title", "этой привычки")
        await state.set_state(EditHabitFSM.choose_field)
        await callback.message.answer(
            f"Что вы хотите изменить в привычке «{title}»?",
            reply_markup=get_edit_field_keyboard(),
        )
        return

    if current_state == EditHabitFSM.choose_field.state:
        await _show_habit_list(
            telegram_id=callback.from_user.id,
            target=callback.message,
            state=state,
        )
        return

    # --- Unknown state — cancel the wizard ---
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.answer(
        "🏠 Главное меню бота\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )


# ===================================================================
# Navigation — Cancel button (extended for EditHabitFSM)
# ===================================================================


@router.callback_query(F.data == "nav:cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the current wizard or edit flow.

    Clears the FSM state and returns the user to the habit list (if
    editing) or main menu (if creating).

    Args:
        callback: Incoming callback query from the cancel button.
        state: FSM context for the current user.
    """
    await callback.answer()

    current_state = await state.get_state()
    is_edit = current_state is not None and current_state.startswith("EditHabitFSM:")

    await state.clear()
    await state.set_state(MainFSM.main_menu)

    if is_edit:
        await callback.message.answer("❌ Редактирование отменено.")
        await _show_habit_list(
            telegram_id=callback.from_user.id,
            target=callback.message,
            state=state,
        )
    else:
        await callback.message.answer(
            "❌ Создание привычки отменено.",
            reply_markup=get_main_menu_keyboard(),
        )
