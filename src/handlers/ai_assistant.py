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
    get_ai_fallback_keyboard,
    get_generic_frequency_keyboard,
    get_hygiene_time_keyboard,
    get_main_menu_keyboard,
    get_skip_only_keyboard,
    get_sport_duration_keyboard,
    get_sport_intensity_keyboard,
)
from src.services.ai_service import build_prompt, send_to_ai
from src.states.fsm import AIAssistantFSM, MainFSM

logger = logging.getLogger(__name__)

router = Router()
"""Router for AI assistant wizard handlers."""

AI_WAITING_TEXT = (
    "⏳ Генерирую SMART-план… Это может занять до 30 секунд."
)
"""Placeholder shown while waiting for the OpenRouter response."""

# ---------------------------------------------------------------------------
# Keyword matching for adaptive questions
# ---------------------------------------------------------------------------

_SPORT_KEYWORDS = [
    "бег",
    "спорт",
    "тренировк",
    "фитнес",
    "зарядк",
    "йог",
    "плавани",
    "велосипед",
    "ходьб",
    "приседан",
    "отжиман",
    "гантел",
    "штанг",
    "турник",
    "пресс",
    "растяжк",
]
"""Keywords that trigger sport/training adaptive questions."""

_HYGIENE_KEYWORDS = [
    "зуб",
    "чистк",
    "уход",
    "душ",
    "гигиен",
    "умыва",
    "брит",
    "ногт",
    "волос",
    "расчёс",
    "расчес",
]
"""Keywords that trigger hygiene adaptive questions."""


def get_adaptive_questions(title: str) -> tuple[str, str, str, str]:
    """Determine which adaptive questions to ask based on habit title keywords.

    Args:
        title: The habit title entered by the user.

    Returns:
        A tuple of (q1_text, q2_text, q1_type, q2_type) where type is one of:
        ``"sport_intensity"``, ``"sport_duration"``, ``"hygiene_time"``,
        ``"hygiene_obstacles"``, ``"generic_frequency"``, ``"generic_obstacles"``.
    """
    title_lower = title.lower()

    if any(kw in title_lower for kw in _SPORT_KEYWORDS):
        return (
            "Какой у вас уровень физической подготовки?",
            "Сколько минут в день вы готовы уделять этой привычке?",
            "sport_intensity",
            "sport_duration",
        )

    if any(kw in title_lower for kw in _HYGIENE_KEYWORDS):
        return (
            "В какое время дня вы планируете это делать?",
            "Что может помешать вам делать это регулярно? "
            "(напишите или нажмите Пропустить)",
            "hygiene_time",
            "hygiene_obstacles",
        )

    return (
        "Как часто вы планируете выполнять эту привычку?",
        "Какие препятствия могут помешать вам её выполнять? "
        "(напишите или нажмите Пропустить)",
        "generic_frequency",
        "generic_obstacles",
    )


# ---------------------------------------------------------------------------
# Back navigation mapping
# ---------------------------------------------------------------------------

_BACK_MAP = {
    AIAssistantFSM.ask_adaptive_q1: AIAssistantFSM.start,
    AIAssistantFSM.ask_adaptive_q2: AIAssistantFSM.ask_adaptive_q1,
    AIAssistantFSM.confirm_recommendations: AIAssistantFSM.ask_adaptive_q2,
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


def _event_bot_chat(event: Message | CallbackQuery):
    """Return ``(bot, chat_id)`` for a Message or CallbackQuery event."""
    if isinstance(event, CallbackQuery):
        return event.bot, event.message.chat.id
    return event.bot, event.chat.id


async def _deliver_ai_result(
    placeholder: Message | None,
    event: Message | CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
) -> None:
    """Edit the waiting placeholder to the final text, with send+delete fallback.

    Prefer editing ``placeholder``. If edit is impossible, send a new message
    and best-effort delete the placeholder so the chat is not left with a
    stale waiting indicator.

    Args:
        placeholder: Message previously shown as the waiting indicator.
        event: Original Message or CallbackQuery (used for bot/chat fallback).
        text: Final message body.
        reply_markup: Optional inline keyboard.
        parse_mode: Optional parse mode for the final message.
    """
    bot, chat_id = _event_bot_chat(event)

    if placeholder is not None:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=placeholder.chat.id,
                message_id=placeholder.message_id,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return
        except Exception:
            logger.warning(
                "Could not edit AI waiting placeholder; sending a new message",
                exc_info=True,
            )

    await bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )

    if placeholder is not None:
        try:
            await bot.delete_message(
                chat_id=placeholder.chat.id,
                message_id=placeholder.message_id,
            )
        except Exception:
            logger.debug(
                "Could not delete AI waiting placeholder after fallback send",
                exc_info=True,
            )


async def _call_ai_and_transition(
    event: Message | CallbackQuery,
    state: FSMContext,
) -> None:
    """Build the prompt from FSM data, call send_to_ai, and transition.

    Shows a waiting placeholder before the AI call, then replaces it with the
    SMART plan or a friendly error + fallback keyboard.

    On success: store AI response in FSM data and go to confirm_recommendations.
    On failure: show friendly error message with fallback to manual creation.

    Args:
        event: The triggering Message or CallbackQuery.
        state: FSM context for the current user.
    """
    data = await state.get_data()
    habit_title = data.get("title", "")
    answers = data.get("answers", {})

    prompt = build_prompt(habit_title, answers)

    # Show waiting indicator before the (potentially slow) AI call.
    placeholder: Message | None = None
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            # Caller may already have answered the callback; ignore.
            pass
        try:
            placeholder = await event.message.edit_text(AI_WAITING_TEXT)
        except Exception:
            logger.warning(
                "Could not edit message to AI waiting text; sending new",
                exc_info=True,
            )
            try:
                placeholder = await event.message.answer(AI_WAITING_TEXT)
            except Exception:
                logger.warning(
                    "Could not send AI waiting placeholder",
                    exc_info=True,
                )
                placeholder = None
    else:
        try:
            placeholder = await event.answer(AI_WAITING_TEXT)
        except Exception:
            logger.warning(
                "Could not send AI waiting placeholder",
                exc_info=True,
            )
            placeholder = None

    ai_response = await send_to_ai(prompt)

    if ai_response is None:
        await _deliver_ai_result(
            placeholder,
            event,
            "🤖 ИИ временно недоступен. "
            "Попробуйте позже или создайте привычку вручную.",
            reply_markup=get_ai_fallback_keyboard(),
        )
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

    await _deliver_ai_result(
        placeholder,
        event,
        message_text,
        reply_markup=get_ai_assistant_confirm_keyboard(),
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Helper: get keyboard for a given question type
# ---------------------------------------------------------------------------


def _get_keyboard_for_q_type(q_type: str):
    """Return the appropriate inline keyboard for a question type.

    Args:
        q_type: One of the adaptive question type strings.

    Returns:
        An InlineKeyboardMarkup for the question, or None for text-input types.
    """
    if q_type == "sport_intensity":
        return get_sport_intensity_keyboard()
    if q_type == "sport_duration":
        return get_sport_duration_keyboard()
    if q_type == "hygiene_time":
        return get_hygiene_time_keyboard()
    if q_type == "generic_frequency":
        return get_generic_frequency_keyboard()
    # For text-input types (hygiene_obstacles, generic_obstacles),
    # show a skip-only keyboard
    if q_type in ("hygiene_obstacles", "generic_obstacles"):
        return get_skip_only_keyboard()
    return None


# ---------------------------------------------------------------------------
# Helper: confirmation keyboard (Yes / No)
# ---------------------------------------------------------------------------


def get_ai_assistant_confirm_keyboard():
    """Build an inline keyboard for confirming AI recommendations.

    Returns:
        InlineKeyboardMarkup with Yes, No, Back, and Cancel buttons.
    """
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data="assist:yes")
    builder.button(text="❌ Нет", callback_data="assist:no")
    builder.button(text="⬅️ Назад", callback_data="nav:back")
    builder.button(text="❌ Отмена", callback_data="nav:cancel")
    builder.adjust(2, 2)
    return builder.as_markup()


# ===========================================================================
# Back and Cancel handlers — registered first to take priority over
# state-specific handlers.
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
    elif target == AIAssistantFSM.ask_adaptive_q1:
        data = await state.get_data()
        q1_text = data.get("q1_text", "")
        q1_type = data.get("q1_type", "")
        keyboard = _get_keyboard_for_q_type(q1_type)
        await callback.message.edit_text(q1_text, reply_markup=keyboard)
    elif target == AIAssistantFSM.ask_adaptive_q2:
        data = await state.get_data()
        q2_text = data.get("q2_text", "")
        q2_type = data.get("q2_type", "")
        keyboard = _get_keyboard_for_q_type(q2_type)
        await callback.message.edit_text(q2_text, reply_markup=keyboard)


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
# Entry point — "Запросить помощь ассистента" button (new_habit:ai)
# ===========================================================================


@router.callback_query(F.data == "new_habit:ai")
async def ai_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry point: start the AI assistant wizard.

    Clears any previous state and asks the user for a habit title.

    Args:
        callback: Incoming callback query from the new habit choice menu.
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
    """Validate and store the habit title, then ask the first adaptive question.

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

    # Determine adaptive questions based on title keywords
    q1_text, q2_text, q1_type, q2_type = get_adaptive_questions(title)

    await state.update_data(
        title=title,
        q1_text=q1_text,
        q2_text=q2_text,
        q1_type=q1_type,
        q2_type=q2_type,
        answers={},
    )
    await state.set_state(AIAssistantFSM.ask_adaptive_q1)

    keyboard = _get_keyboard_for_q_type(q1_type)
    await message.answer(q1_text, reply_markup=keyboard)


# ===========================================================================
# State: ask_adaptive_q1 — first adaptive question
# ===========================================================================


@router.callback_query(AIAssistantFSM.ask_adaptive_q1, F.data.startswith("assist:"))
async def process_adaptive_q1_callback(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Handle callback-based answer for the first adaptive question.

    Args:
        callback: Incoming callback query.
        state: FSM context for the current user.
    """
    await callback.answer()
    data = callback.data
    data_state = await state.get_data()
    answers = data_state.get("answers", {})

    if data == "assist:skip":
        answers["q1"] = "Пропущено"
    else:
        # Extract the value from the callback data
        # Format: assist:category:value or assist:value
        parts = data.split(":", 2)
        if len(parts) >= 3:
            value = parts[2]
        else:
            value = parts[1] if len(parts) > 1 else data

        # Map to human-readable labels
        label_map = {
            "beginner": "Начинающий",
            "intermediate": "Средний",
            "advanced": "Продвинутый",
            "15": "15 мин",
            "30": "30 мин",
            "45": "45 мин",
            "60": "60 мин",
            "morning": "Утром",
            "evening": "Вечером",
            "both": "Утром и вечером",
            "daily": "Каждый день",
            "several_per_week": "Несколько раз в неделю",
            "once_per_week": "Раз в неделю",
        }
        answers["q1"] = label_map.get(value, value)

    await state.update_data(answers=answers)
    await state.set_state(AIAssistantFSM.ask_adaptive_q2)

    q2_text = data_state.get("q2_text", "")
    q2_type = data_state.get("q2_type", "")
    keyboard = _get_keyboard_for_q_type(q2_type)
    await callback.message.edit_text(q2_text, reply_markup=keyboard)


@router.message(AIAssistantFSM.ask_adaptive_q1)
async def process_adaptive_q1_text(message: Message, state: FSMContext) -> None:
    """Handle text-based answer for the first adaptive question (fallback).

    Args:
        message: Incoming text message.
        state: FSM context for the current user.
    """
    text = (message.text or "").strip()
    data_state = await state.get_data()
    answers = data_state.get("answers", {})

    answers["q1"] = text if text else "Пропущено"
    await state.update_data(answers=answers)
    await state.set_state(AIAssistantFSM.ask_adaptive_q2)

    q2_text = data_state.get("q2_text", "")
    q2_type = data_state.get("q2_type", "")
    keyboard = _get_keyboard_for_q_type(q2_type)
    await message.answer(q2_text, reply_markup=keyboard)


# ===========================================================================
# State: ask_adaptive_q2 — second adaptive question
# ===========================================================================


@router.callback_query(AIAssistantFSM.ask_adaptive_q2, F.data.startswith("assist:"))
async def process_adaptive_q2_callback(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Handle callback-based answer for the second adaptive question.

    Args:
        callback: Incoming callback query.
        state: FSM context for the current user.
    """
    await callback.answer()
    data = callback.data
    data_state = await state.get_data()
    answers = data_state.get("answers", {})

    if data == "assist:skip":
        answers["q2"] = "Пропущено"
    else:
        parts = data.split(":", 2)
        if len(parts) >= 3:
            value = parts[2]
        else:
            value = parts[1] if len(parts) > 1 else data

        label_map = {
            "beginner": "Начинающий",
            "intermediate": "Средний",
            "advanced": "Продвинутый",
            "15": "15 мин",
            "30": "30 мин",
            "45": "45 мин",
            "60": "60 мин",
            "morning": "Утром",
            "evening": "Вечером",
            "both": "Утром и вечером",
            "daily": "Каждый день",
            "several_per_week": "Несколько раз в неделю",
            "once_per_week": "Раз в неделю",
        }
        answers["q2"] = label_map.get(value, value)

    await state.update_data(answers=answers)
    await _call_ai_and_transition(callback, state)


@router.message(AIAssistantFSM.ask_adaptive_q2)
async def process_adaptive_q2_text(message: Message, state: FSMContext) -> None:
    """Handle text-based answer for the second adaptive question.

    Args:
        message: Incoming text message.
        state: FSM context for the current user.
    """
    text = (message.text or "").strip()
    data_state = await state.get_data()
    answers = data_state.get("answers", {})

    answers["q2"] = text if text else "Пропущено"
    await state.update_data(answers=answers)
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
                user = User(
                    telegram_id=telegram_id,
                    username=callback.from_user.username,
                    language="ru",
                    timezone="UTC",
                )
                session.add(user)
                await session.flush()
            elif callback.from_user.username and user.username != callback.from_user.username:
                user.username = callback.from_user.username


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
