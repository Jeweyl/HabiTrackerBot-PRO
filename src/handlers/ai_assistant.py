"""AI assistant handlers: FSM wizard for SMART goal creation via OpenRouter."""

import logging
from datetime import date, datetime, time, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import Habit, Task, User, UserAIState
from src.db.session import get_db
from src.keyboards.inline import (
    get_ai_assistant_keyboard,
    get_duration_keyboard,
    get_main_menu_keyboard,
)
from src.services.ai_service import build_prompt, send_to_ai
from src.states.fsm import AIAssistantFSM, MainFSM

logger = logging.getLogger(__name__)

router = Router()
"""Router for AI assistant wizard handlers."""

# ---------------------------------------------------------------------------
# Back navigation mapping
# ---------------------------------------------------------------------------

_BACK_MAP = {
    AIAssistantFSM.ask_experience: AIAssistantFSM.start,
    AIAssistantFSM.ask_duration: AIAssistantFSM.ask_experience,
    AIAssistantFSM.ask_details: AIAssistantFSM.ask_duration,
    AIAssistantFSM.ask_health: AIAssistantFSM.ask_details,
    AIAssistantFSM.ask_health_details: AIAssistantFSM.ask_health,
    AIAssistantFSM.confirm_recommendations: AIAssistantFSM.ask_health,
}


# ---------------------------------------------------------------------------
# Helper: return to main menu
# ---------------------------------------------------------------------------


async def _return_to_main_menu(
    event: Message | CallbackQuery, state: FSMContext
) -> None:
    """Clear FSM state and show the main menu.

    Args:
        event: Message or CallbackQuery to answer/respond to.
        state: FSM context for the current user.
    """
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    text = "🏠 Главное меню бота\nВыберите действие:"
    markup = get_main_menu_keyboard()
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.edit_text(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


# ---------------------------------------------------------------------------
# Helper: call AI service and transition to confirm or error
# ---------------------------------------------------------------------------


async def _call_ai_and_transition(
    event: Message | CallbackQuery,
    state: FSMContext,
) -> None:
    """Build the prompt from FSM data, call send_to_ai, and transition.

    On success: store AI response in FSM data and go to confirm_recommendations.
    On failure: show error message and return to main menu.

    Args:
        event: The triggering Message or CallbackQuery.
        state: FSM context for the current user.
    """
    data = await state.get_data()
    prompt = build_prompt(data)
    ai_response = await send_to_ai(prompt)

    if ai_response is None:
        if isinstance(event, CallbackQuery):
            await event.answer()
        await event.message.edit_text(
            "❌ Не удалось получить рекомендации. "
            "Попробуйте позже или создайте привычку вручную.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        return

    await state.update_data(ai_response=ai_response)
    await state.set_state(AIAssistantFSM.confirm_recommendations)

    refined = ai_response.get("refined_habit", "—")
    metric_name = ai_response.get("metric_name", "—")
    metric_unit = ai_response.get("metric_unit", "—")
    target = ai_response.get("target_per_day", "—")
    period = ai_response.get("period", "—")
    comment = ai_response.get("comment", "—")

    message_text = (
        "🤖 *Ваш SMART-план:*\n\n"
        f"*Привычка:* {refined}\n"
        f"*Метрика:* {metric_name} ({metric_unit})\n"
        f"*Цель в день:* {target}\n"
        f"*Период:* {period}\n"
        f"*Комментарий:* {comment}\n\n"
        "Создать привычку на основе этих рекомендаций?"
    )

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.edit_text(
            message_text,
            reply_markup=get_ai_assistant_keyboard(),
            parse_mode="Markdown",
        )
    else:
        await event.answer(
            message_text,
            reply_markup=get_ai_assistant_keyboard(),
            parse_mode="Markdown",
        )


# ===========================================================================
# Back and Cancel handlers — registered first to take priority over
# state-specific handlers.  They use ``F.data`` filters only and determine
# the current state via ``state.get_state()``.
# ===========================================================================


@router.callback_query(F.data == "nav:back")
async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Navigate to the previous step in the AI assistant wizard.

    Determines the current state via ``state.get_state()`` and transitions
    to the previous step according to ``_BACK_MAP``.  If the current state
    is not in the map, returns to the main menu.

    Args:
        callback: Incoming callback query from a back button.
        state: FSM context for the current user.
    """
    await callback.answer()
    current = await state.get_state()

    # Find the FSM state enum member matching the current string state
    target = None
    for fsm_state, back_state in _BACK_MAP.items():
        if fsm_state.state == current:
            target = back_state
            break

    if target is None:
        await _return_to_main_menu(callback, state)
        return

    await state.set_state(target)

    if target == AIAssistantFSM.start:
        await callback.message.edit_text(
            "Какую привычку вы хотите развить? "
            "Опишите её одной фразой (например, 'Я хочу бегать каждое утро').",
        )
    elif target == AIAssistantFSM.ask_experience:
        await callback.message.edit_text(
            "У вас есть опыт в этой сфере?",
            reply_markup=get_ai_assistant_keyboard(),
        )
    elif target == AIAssistantFSM.ask_duration:
        await callback.message.edit_text(
            "Как давно вы этим занимаетесь?",
            reply_markup=get_duration_keyboard(),
        )
    elif target == AIAssistantFSM.ask_details:
        await callback.message.edit_text(
            "Пожалуйста, уточните детали: сколько времени тратите, "
            "делаете ли перерывы, как часто занимаетесь?",
        )
    elif target == AIAssistantFSM.ask_health:
        await callback.message.edit_text(
            "Есть ли у вас проблемы со здоровьем, которые "
            "могут повлиять на привычку?",
            reply_markup=get_ai_assistant_keyboard(),
        )
    elif target == AIAssistantFSM.ask_health_details:
        await callback.message.edit_text(
            "Пожалуйста, опишите ваши ограничения по здоровью.",
        )


@router.callback_query(F.data == "nav:cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the AI assistant wizard and return to the main menu.

    Args:
        callback: Incoming callback query from a cancel button.
        state: FSM context for the current user.
    """
    await _return_to_main_menu(callback, state)
    logger.debug("AI assistant wizard cancelled by user %d", callback.from_user.id)


# ===========================================================================
# Entry point — "Помощь" button (main_menu:help)
# ===========================================================================


@router.callback_query(F.data == "main_menu:help")
async def ai_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry point: start the AI assistant wizard.

    Clears any previous state and asks the user for a habit title.

    Args:
        callback: Incoming callback query from the main menu button.
        state: FSM context for the current user.
    """
    await callback.answer()
    await state.clear()
    await state.set_state(AIAssistantFSM.start)
    await callback.message.edit_text(
        "Какую привычку вы хотите развить? "
        "Опишите её одной фразой (например, 'Я хочу бегать каждое утро').",
    )


# ===========================================================================
# State: start — receive habit title
# ===========================================================================


@router.message(AIAssistantFSM.start)
async def process_title(message: Message, state: FSMContext) -> None:
    """Validate and store the habit title, then ask about experience.

    Args:
        message: Incoming text message with the habit title.
        state: FSM context for the current user.
    """
    title = (message.text or "").strip()

    if not title:
        await message.answer(
            "Пожалуйста, опишите привычку (минимум 1 символ).",
        )
        return

    if len(title) > 200:
        await message.answer(
            "Слишком длинное описание. Пожалуйста, уложитесь в 200 символов.",
        )
        return

    await state.update_data(title=title)
    await state.set_state(AIAssistantFSM.ask_experience)
    await message.answer(
        "У вас есть опыт в этой сфере?",
        reply_markup=get_ai_assistant_keyboard(),
    )


# ===========================================================================
# State: ask_experience — yes / no / skip
# ===========================================================================


@router.callback_query(AIAssistantFSM.ask_experience)
async def process_experience(callback: CallbackQuery, state: FSMContext) -> None:
    """Store the user's experience answer and ask about duration.

    Args:
        callback: Incoming callback query.
        state: FSM context for the current user.
    """
    await callback.answer()
    data = callback.data

    if data == "assist:yes":
        await state.update_data(experience="yes")
    elif data == "assist:no":
        await state.update_data(experience="no")
    elif data == "assist:skip":
        await state.update_data(experience=None)
    else:
        return  # ignore other callbacks

    await state.set_state(AIAssistantFSM.ask_duration)
    await callback.message.edit_text(
        "Как давно вы этим занимаетесь?",
        reply_markup=get_duration_keyboard(),
    )


# ===========================================================================
# State: ask_duration — duration options
# ===========================================================================


@router.callback_query(AIAssistantFSM.ask_duration)
async def process_duration(callback: CallbackQuery, state: FSMContext) -> None:
    """Store the duration answer and ask for more details.

    Args:
        callback: Incoming callback query.
        state: FSM context for the current user.
    """
    await callback.answer()
    data = callback.data

    if data.startswith("duration:"):
        value = data.split(":", 1)[1]
        if value == "skip":
            await state.update_data(duration=None)
        else:
            await state.update_data(duration=value)
    else:
        return  # ignore other callbacks

    await state.set_state(AIAssistantFSM.ask_details)
    await callback.message.edit_text(
        "Пожалуйста, уточните детали: сколько времени тратите, "
        "делаете ли перерывы, как часто занимаетесь?",
    )


# ===========================================================================
# State: ask_details — free-text details
# ===========================================================================


@router.message(AIAssistantFSM.ask_details)
async def process_details(message: Message, state: FSMContext) -> None:
    """Store the free-text details and ask about health.

    Args:
        message: Incoming text message with details.
        state: FSM context for the current user.
    """
    details = (message.text or "").strip() or None
    await state.update_data(details=details)
    await state.set_state(AIAssistantFSM.ask_health)
    await message.answer(
        "Есть ли у вас проблемы со здоровьем, которые " "могут повлиять на привычку?",
        reply_markup=get_ai_assistant_keyboard(),
    )


# ===========================================================================
# State: ask_health — yes (→ details) / no / skip
# ===========================================================================


@router.callback_query(AIAssistantFSM.ask_health)
async def process_health(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle the health question: yes → ask for details, no/skip → proceed.

    Args:
        callback: Incoming callback query.
        state: FSM context for the current user.
    """
    await callback.answer()
    data = callback.data

    if data == "assist:yes":
        await state.set_state(AIAssistantFSM.ask_health_details)
        await callback.message.edit_text(
            "Пожалуйста, опишите ваши ограничения по здоровью.",
        )
    elif data in ("assist:no", "assist:skip"):
        await state.update_data(health=None)
        await _call_ai_and_transition(callback, state)


# ===========================================================================
# State: ask_health_details — free-text health info, then call AI
# ===========================================================================


@router.message(AIAssistantFSM.ask_health_details)
async def process_health_details(message: Message, state: FSMContext) -> None:
    """Store the health details, call the AI service, and move to confirmation.

    Args:
        message: Incoming text message with health details.
        state: FSM context for the current user.
    """
    health = (message.text or "").strip() or None
    await state.update_data(health=health)
    await _call_ai_and_transition(message, state)


# ===========================================================================
# State: confirm_recommendations — yes (create habit) / no (cancel)
# ===========================================================================


@router.callback_query(AIAssistantFSM.confirm_recommendations)
async def process_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle confirmation: create habit + task on yes, cancel on no.

    Args:
        callback: Incoming callback query.
        state: FSM context for the current user.
    """
    await callback.answer()
    data = callback.data

    if data == "assist:yes":
        ai_data = await state.get_data()
        ai_response = ai_data.get("ai_response", {})

        refined_title = ai_response.get(
            "refined_habit", ai_data.get("title", "New Habit")
        )
        period = ai_response.get("period", "daily")

        # Map AI period to habit frequency
        frequency_map = {"daily": "daily", "weekly": "weekdays"}
        frequency = frequency_map.get(period, "daily")

        telegram_id = callback.from_user.id

        async with get_db() as session:
            # Resolve internal user ID
            stmt = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user is None:
                user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
                session.add(user)
                await session.flush()

            # Create habit
            habit = Habit(
                user_id=user.id,
                title=refined_title[:200],
                start_time=time(8, 0),
                end_time=time(9, 0),
                frequency=frequency,
            )
            session.add(habit)
            await session.flush()

            # Create task for today
            today = date.today()
            task = Task(
                user_id=user.id,
                habit_id=habit.id,
                title=refined_title[:200],
                date=today,
                start_time=time(8, 0),
                end_time=time(9, 0),
                is_completed=False,
                is_placeholder=False,
            )
            session.add(task)

            # Store AI state
            stmt_ai = select(UserAIState).where(UserAIState.user_id == user.id)
            result_ai = await session.execute(stmt_ai)
            ai_state = result_ai.scalar_one_or_none()

            if ai_state is None:
                ai_state = UserAIState(user_id=user.id, summary=ai_response)
                session.add(ai_state)
            else:
                ai_state.summary = ai_response
                ai_state.updated_at = datetime.now(timezone.utc)

            await session.commit()

            logger.info(
                "Created habit %d and task %d for user %d via AI assistant",
                habit.id,
                task.id,
                user.id,
            )

        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            "✅ Привычка успешно создана!\n\n"
            f"*{refined_title}*\n"
            f"Период: {period}\n"
            f"Время: 08:00–09:00",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown",
        )

    elif data == "assist:no":
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            "Хорошо, может быть, в другой раз!",
            reply_markup=get_main_menu_keyboard(),
        )


