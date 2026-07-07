"""Handlers for the "New Habit" creation wizard."""

import logging
from datetime import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import Habit, User
from src.db.session import get_db
from src.keyboards.inline import (
    get_frequency_keyboard,
    get_main_menu_keyboard,
    get_time_selection_keyboard,
)
from src.states.fsm import MainFSM, NewHabitFSM

logger = logging.getLogger(__name__)

router = Router()
"""Router for habit-related handlers (new habit wizard)."""

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

    freq_labels = {
        "daily": "📅 Ежедневно",
        "weekdays": "📆 По будням",
        "weekends": "🎉 По выходным",
    }
    freq_label = freq_labels.get(frequency, frequency)

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
# Navigation — Back button
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:back")
async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate one step back in the wizard.

    Determines the current FSM state and moves to the previous step,
    re-prompting the user with the appropriate message and keyboard.

    Args:
        callback: Incoming callback query from the back button.
        state: FSM context for the current user.
    """
    await callback.answer()

    current_state = await state.get_state()

    if current_state == NewHabitFSM.start_time.state:
        await state.set_state(NewHabitFSM.title)
        await callback.message.answer(
            "📝 Введите название привычки (от 1 до 200 символов):",
        )
    elif current_state == NewHabitFSM.end_time.state:
        await state.set_state(NewHabitFSM.start_time)
        await callback.message.answer(
            "⏰ Выберите время начала привычки:",
            reply_markup=get_time_selection_keyboard(),
        )
    elif current_state == NewHabitFSM.frequency.state:
        await state.set_state(NewHabitFSM.end_time)
        fsm_data = await state.get_data()
        st = fsm_data.get("start_time")
        await callback.message.answer(
            "⏰ Выберите время окончания привычки:",
            reply_markup=get_time_selection_keyboard(
                min_time=st, show_null_option=True
            ),
        )
    else:
        # Unknown state — cancel the wizard
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await callback.message.answer(
            "🏠 Главное меню бота\nВыберите действие:",
            reply_markup=get_main_menu_keyboard(),
        )


# ---------------------------------------------------------------------------
# Navigation — Cancel button
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the habit creation wizard.

    Clears the FSM state, sends a cancellation message, and returns the
    user to the main menu.

    Args:
        callback: Incoming callback query from the cancel button.
        state: FSM context for the current user.
    """
    await callback.answer()

    await state.clear()
    await state.set_state(MainFSM.main_menu)

    await callback.message.answer(
        "❌ Создание привычки отменено.",
        reply_markup=get_main_menu_keyboard(),
    )
