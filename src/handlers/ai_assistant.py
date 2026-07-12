"""AI assistant handlers: multi-turn habit wizard via OpenRouter (B2).

Flow:
  title → AI turn (ask_questions | propose_plan) → user answers (max 3
  clarifying rounds) → soft plan preview → confirm → create habit.

No habit is written to the DB until the user confirms the preview.
Every AI call shows a user-visible waiting indicator.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import Habit, Task, User, UserAIState
from src.db.session import get_db
from src.i18n import normalize_lang
from src.keyboards.inline import (
    get_ai_choice_keyboard,
    get_ai_fallback_keyboard,
    get_ai_plan_confirm_keyboard,
    get_hour_selection_keyboard,
    get_main_menu_keyboard,
    get_minute_selection_keyboard,
    get_skip_only_keyboard,
)
from src.services.ai_schema import (
    AskQuestions,
    ClarifyingQuestion,
    ProposePlan,
    normalize_question,
)
from src.services.ai_service import (
    MAX_CLARIFYING_ROUNDS,
    build_multiturn_prompt,
    build_user_context_summary,
    send_to_ai_parsed,
)
from src.states.fsm import AIAssistantFSM, MainFSM
from src.utils.time_picker import PENDING_HOUR_KEY, parse_time_callback

logger = logging.getLogger(__name__)

router = Router()
"""Router for AI assistant wizard handlers."""

AI_WAITING_TEXT = (
    "⏳ Генерирую SMART-план… Это может занять до 30 секунд."
)
"""Placeholder shown while waiting for the OpenRouter response."""

AI_UNAVAILABLE_TEXT = (
    "🤖 ИИ временно недоступен. "
    "Попробуйте позже или создайте привычку вручную."
)
"""Friendly error when AI returns None / invalid payload."""


# ---------------------------------------------------------------------------
# Helpers: main menu / bot-chat / deliver
# ---------------------------------------------------------------------------


async def _return_to_main_menu(
    event: Message | CallbackQuery, state: FSMContext
) -> None:
    """Clear FSM state and show the main menu."""
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    text = "🏠 Главное меню бота\nВыберите действие:"
    markup = get_main_menu_keyboard()
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except Exception:
            await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


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
    """Edit the waiting placeholder to the final text, with send+delete fallback."""
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


async def _show_waiting(
    event: Message | CallbackQuery,
) -> Message | None:
    """Show the AI waiting indicator; never raise to the caller."""
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        try:
            return await event.message.edit_text(AI_WAITING_TEXT)
        except Exception:
            logger.warning(
                "Could not edit message to AI waiting text; sending new",
                exc_info=True,
            )
            try:
                return await event.message.answer(AI_WAITING_TEXT)
            except Exception:
                logger.warning(
                    "Could not send AI waiting placeholder",
                    exc_info=True,
                )
                return None
    try:
        return await event.answer(AI_WAITING_TEXT)
    except Exception:
        logger.warning(
            "Could not send AI waiting placeholder",
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Context loading (language, timezone, habits/tasks summary)
# ---------------------------------------------------------------------------


async def _load_user_ai_context(telegram_id: int) -> dict[str, Any]:
    """Load language, timezone and habits/tasks summary for the AI prompt.

    Never raises. Missing user → safe defaults.
    """
    language = "ru"
    tz = "UTC"
    habits: list[Any] = []
    tasks: list[Any] = []

    try:
        async with get_db() as session:
            stmt = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user is None:
                summary = build_user_context_summary(
                    language=language,
                    timezone=tz,
                    habits=[],
                    tasks=[],
                )
                return {
                    "language": language,
                    "timezone": tz,
                    "habits_tasks_summary": summary,
                }

            language = normalize_lang(user.language)
            tz = user.timezone or "UTC"

            h_stmt = select(Habit).where(Habit.user_id == user.id)
            h_result = await session.execute(h_stmt)
            habits = list(h_result.scalars().all())

            today = date.today()
            t_stmt = (
                select(Task)
                .where(Task.user_id == user.id, Task.date == today)
                .order_by(Task.start_time)
            )
            t_result = await session.execute(t_stmt)
            tasks = list(t_result.scalars().all())
    except Exception:
        logger.warning(
            "Failed to load AI user context for telegram_id=%s",
            telegram_id,
            exc_info=True,
        )

    summary = build_user_context_summary(
        language=language,
        timezone=tz,
        habits=habits,
        tasks=tasks,
    )
    return {
        "language": language,
        "timezone": tz,
        "habits_tasks_summary": summary,
    }


# ---------------------------------------------------------------------------
# Question UI
# ---------------------------------------------------------------------------


def _question_to_dict(q: ClarifyingQuestion | dict | str) -> dict[str, Any]:
    """Serialize a clarifying question for FSM storage."""
    if isinstance(q, ClarifyingQuestion):
        return q.model_dump()
    normalized = normalize_question(q)
    if normalized is None:
        return {"text": str(q), "kind": "text", "options": None}
    return normalized.model_dump()


def _keyboard_for_question(q: dict[str, Any]):
    """Return inline keyboard for a stored question dict."""
    kind = q.get("kind") or "text"
    if kind == "choice":
        options = q.get("options") or []
        if options:
            return get_ai_choice_keyboard(list(options))
        return get_skip_only_keyboard()
    if kind == "time":
        return get_hour_selection_keyboard()
    return get_skip_only_keyboard()


def _format_question_text(q: dict[str, Any], context: str | None = None) -> str:
    """Build message body for a clarifying question."""
    parts: list[str] = []
    if context:
        parts.append(str(context).strip())
    text = (q.get("text") or "").strip() or "Уточните, пожалуйста."
    parts.append(text)
    kind = q.get("kind") or "text"
    if kind == "text":
        parts.append("(напишите ответ или нажмите Пропустить)")
    elif kind == "time":
        parts.append("(выберите время с шагом 15 минут)")
    return "\n\n".join(p for p in parts if p)


async def _present_next_question(
    event: Message | CallbackQuery,
    state: FSMContext,
    *,
    placeholder: Message | None = None,
) -> None:
    """Show the next pending question or re-run AI if the queue is empty."""
    data = await state.get_data()
    pending: list[dict] = list(data.get("pending_questions") or [])
    context = data.get("ask_context")

    if not pending:
        await _run_ai_turn(event, state, placeholder=placeholder)
        return

    current = pending[0]
    remaining = pending[1:]
    await state.update_data(
        pending_questions=remaining,
        current_question=current,
        **{PENDING_HOUR_KEY: None},
    )
    await state.set_state(AIAssistantFSM.clarifying)

    text = _format_question_text(current, context=context)
    markup = _keyboard_for_question(current)

    if placeholder is not None:
        await _deliver_ai_result(placeholder, event, text, reply_markup=markup)
        return

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except Exception:
            await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


def _format_plan_preview(plan: ProposePlan | dict[str, Any]) -> str:
    """Soft preview text for a ProposePlan (no DB write)."""
    if isinstance(plan, ProposePlan):
        data = plan.model_dump()
    else:
        data = plan

    title = data.get("title") or "—"
    start = data.get("start_time") or "—"
    end = data.get("end_time")
    freq = data.get("frequency") or "daily"
    duration = data.get("duration_minutes")
    comment = data.get("comment") or "—"

    time_line = f"{start}" + (f"–{end}" if end else "")
    duration_line = f"{duration} мин" if duration is not None else "—"

    return (
        "🤖 *Предложенный план (черновик):*\n\n"
        f"*Привычка:* {title}\n"
        f"*Время:* {time_line}\n"
        f"*Частота:* {freq}\n"
        f"*Длительность:* {duration_line}\n"
        f"*Комментарий:* {comment}\n\n"
        "Создать привычку на основе этого плана?"
    )


# ---------------------------------------------------------------------------
# Core AI turn
# ---------------------------------------------------------------------------


async def _run_ai_turn(
    event: Message | CallbackQuery,
    state: FSMContext,
    *,
    placeholder: Message | None = None,
    force_propose: bool = False,
) -> None:
    """Call AI with multiturn prompt and branch on AskQuestions / ProposePlan.

    Always shows a waiting indicator before the network call (unless a
    placeholder is already provided). Never raises for AI/network failures.
    """
    data = await state.get_data()
    habit_title = data.get("title") or ""
    answers = data.get("answers") or {}
    language = data.get("language") or "ru"
    tz = data.get("timezone") or "UTC"
    summary = data.get("habits_tasks_summary") or ""
    clarifying_round = int(data.get("clarifying_round") or 0)

    if placeholder is None:
        placeholder = await _show_waiting(event)

    # After max rounds, force propose (anti-loop).
    if clarifying_round >= MAX_CLARIFYING_ROUNDS:
        force_propose = True

    prompt = build_multiturn_prompt(
        habit_title=habit_title,
        answers=answers,
        language=language,
        timezone=tz,
        habits_tasks_summary=summary,
        clarifying_round=clarifying_round,
        force_propose=force_propose,
    )

    try:
        ai_response = await send_to_ai_parsed(prompt)
    except Exception:
        logger.error("send_to_ai_parsed raised unexpectedly", exc_info=True)
        ai_response = None

    if ai_response is None:
        await _deliver_ai_result(
            placeholder,
            event,
            AI_UNAVAILABLE_TEXT,
            reply_markup=get_ai_fallback_keyboard(),
        )
        return

    if isinstance(ai_response, AskQuestions):
        # 4th ask (or any ask while force_propose): re-call once with force.
        if force_propose or clarifying_round >= MAX_CLARIFYING_ROUNDS:
            logger.info(
                "AI returned ask_questions at/after max rounds "
                "(round=%s); force-proposing",
                clarifying_round,
            )
            # One forced re-call with waiting already shown; if still ask/None → fallback
            prompt2 = build_multiturn_prompt(
                habit_title=habit_title,
                answers=answers,
                language=language,
                timezone=tz,
                habits_tasks_summary=summary,
                clarifying_round=clarifying_round,
                force_propose=True,
            )
            try:
                ai_response = await send_to_ai_parsed(prompt2)
            except Exception:
                logger.error(
                    "force propose send_to_ai_parsed raised",
                    exc_info=True,
                )
                ai_response = None

            if ai_response is None or isinstance(ai_response, AskQuestions):
                await _deliver_ai_result(
                    placeholder,
                    event,
                    AI_UNAVAILABLE_TEXT,
                    reply_markup=get_ai_fallback_keyboard(),
                )
                return
            # fall through to ProposePlan handling below
        else:
            questions = list(ai_response.questions or [])
            if not questions:
                await _deliver_ai_result(
                    placeholder,
                    event,
                    AI_UNAVAILABLE_TEXT,
                    reply_markup=get_ai_fallback_keyboard(),
                )
                return

            pending = [_question_to_dict(q) for q in questions]
            pending = [q for q in pending if q.get("text")]
            if not pending:
                await _deliver_ai_result(
                    placeholder,
                    event,
                    AI_UNAVAILABLE_TEXT,
                    reply_markup=get_ai_fallback_keyboard(),
                )
                return

            await state.update_data(
                clarifying_round=clarifying_round + 1,
                pending_questions=pending,
                ask_context=ai_response.context,
                current_question=None,
            )
            await _present_next_question(
                event, state, placeholder=placeholder
            )
            return

    if isinstance(ai_response, ProposePlan):
        plan_data = ai_response.model_dump()
        await state.update_data(
            proposed_plan=plan_data,
            pending_questions=[],
            current_question=None,
        )
        await state.set_state(AIAssistantFSM.confirm_plan)
        await _deliver_ai_result(
            placeholder,
            event,
            _format_plan_preview(ai_response),
            reply_markup=get_ai_plan_confirm_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Unexpected type
    await _deliver_ai_result(
        placeholder,
        event,
        AI_UNAVAILABLE_TEXT,
        reply_markup=get_ai_fallback_keyboard(),
    )


async def _record_answer_and_continue(
    event: Message | CallbackQuery,
    state: FSMContext,
    answer: str,
) -> None:
    """Store the answer for the current question and continue the flow."""
    data = await state.get_data()
    answers = dict(data.get("answers") or {})
    current = data.get("current_question") or {}
    q_text = (current.get("text") if isinstance(current, dict) else None) or "answer"
    # Unique-ish key if the same question text repeats
    key = q_text
    if key in answers:
        key = f"{q_text} ({len(answers) + 1})"
    answers[key] = answer if answer else "Пропущено"
    await state.update_data(
        answers=answers,
        current_question=None,
        **{PENDING_HOUR_KEY: None},
    )

    pending = list(data.get("pending_questions") or [])
    if pending:
        await _present_next_question(event, state)
    else:
        await _run_ai_turn(event, state)


# ---------------------------------------------------------------------------
# Cancel / back
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the AI assistant wizard and return to the main menu."""
    await _return_to_main_menu(callback, state)
    logger.debug("AI assistant wizard cancelled by user %d", callback.from_user.id)


@router.callback_query(F.data == "nav:back")
async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Simple back: from clarifying/confirm → re-prompt title; else main menu."""
    await callback.answer()
    current = await state.get_state()

    if current == AIAssistantFSM.clarifying.state:
        # Re-show title prompt (restart multi-turn from title)
        await state.set_state(AIAssistantFSM.start)
        await callback.message.edit_text(
            "Какую привычку вы хотите развить? "
            "Опишите её одной фразой (например, 'Я хочу бегать каждое утро').",
        )
        return

    if current == AIAssistantFSM.confirm_plan.state:
        await state.set_state(AIAssistantFSM.start)
        await callback.message.edit_text(
            "Какую привычку вы хотите развить? "
            "Опишите её одной фразой (например, 'Я хочу бегать каждое утро').",
        )
        return

    await _return_to_main_menu(callback, state)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "new_habit:ai")
async def ai_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry point: start the AI multi-turn habit wizard."""
    await callback.answer()
    await state.clear()
    await state.set_state(AIAssistantFSM.start)
    await callback.message.edit_text(
        "Какую привычку вы хотите развить? "
        "Опишите её одной фразой (например, 'Я хочу бегать каждое утро').",
    )


# ---------------------------------------------------------------------------
# State: start — receive habit title → first AI turn
# ---------------------------------------------------------------------------


@router.message(AIAssistantFSM.start)
async def process_title(message: Message, state: FSMContext) -> None:
    """Validate title, load user context, run first AI turn."""
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

    ctx = await _load_user_ai_context(message.from_user.id)
    await state.update_data(
        title=title,
        answers={},
        clarifying_round=0,
        pending_questions=[],
        current_question=None,
        proposed_plan=None,
        language=ctx["language"],
        timezone=ctx["timezone"],
        habits_tasks_summary=ctx["habits_tasks_summary"],
    )
    await _run_ai_turn(message, state)


# ---------------------------------------------------------------------------
# State: clarifying — text / choice / skip / time
# ---------------------------------------------------------------------------


@router.callback_query(AIAssistantFSM.clarifying, F.data == "assist:skip")
async def process_clarifying_skip(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Skip the current clarifying question."""
    await callback.answer()
    await _record_answer_and_continue(callback, state, "Пропущено")


@router.callback_query(
    AIAssistantFSM.clarifying, F.data.startswith("assist:choice:")
)
async def process_clarifying_choice(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Handle a choice-button answer."""
    await callback.answer()
    data = await state.get_data()
    current = data.get("current_question") or {}
    options = list(current.get("options") or [])
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        idx = -1
    if 0 <= idx < len(options):
        answer = options[idx]
    else:
        answer = callback.data or "Пропущено"
    await _record_answer_and_continue(callback, state, answer)


@router.callback_query(AIAssistantFSM.clarifying, F.data.startswith("time:"))
async def process_clarifying_time(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Handle two-step 15-min time picker for kind=time questions."""
    kind, value = parse_time_callback(callback.data)

    if kind == "hour" and isinstance(value, int):
        await callback.answer()
        await state.update_data(**{PENDING_HOUR_KEY: value})
        try:
            await callback.message.edit_text(
                f"Выберите минуты для {value:02d}:xx",
                reply_markup=get_minute_selection_keyboard(value),
            )
        except Exception:
            await callback.message.answer(
                f"Выберите минуты для {value:02d}:xx",
                reply_markup=get_minute_selection_keyboard(value),
            )
        return

    if kind == "final" and isinstance(value, time):
        await callback.answer()
        answer = value.strftime("%H:%M")
        await _record_answer_and_continue(callback, state, answer)
        return

    if kind == "null":
        await callback.answer()
        await _record_answer_and_continue(callback, state, "Пропущено")
        return

    # invalid — ignore quietly
    try:
        await callback.answer()
    except Exception:
        pass


@router.message(AIAssistantFSM.clarifying)
async def process_clarifying_text(message: Message, state: FSMContext) -> None:
    """Handle free-text answer for the current clarifying question."""
    text = (message.text or "").strip()
    await _record_answer_and_continue(message, state, text if text else "Пропущено")


# ---------------------------------------------------------------------------
# State: confirm_plan — yes creates habit; no cancels (soft preview only before)
# ---------------------------------------------------------------------------


def _parse_hh_mm_safe(value: str | None, default: time) -> time:
    """Parse HH:MM safely; return *default* on any failure."""
    if not value or not isinstance(value, str):
        return default
    try:
        parts = value.strip().split(":")
        if len(parts) != 2:
            return default
        hour = int(parts[0])
        minute = int(parts[1])
        if hour not in range(24) or minute not in (0, 15, 30, 45):
            return default
        return time(hour, minute)
    except (TypeError, ValueError):
        return default


@router.callback_query(AIAssistantFSM.confirm_plan)
async def process_plan_confirmation(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Confirm preview: create habit on yes; cancel on no. No silent writes."""
    await callback.answer()
    data_cb = callback.data

    if data_cb == "assist:yes":
        fsm_data = await state.get_data()
        plan = fsm_data.get("proposed_plan") or {}
        title = (plan.get("title") or fsm_data.get("title") or "New Habit")[:200]
        start_t = _parse_hh_mm_safe(plan.get("start_time"), time(8, 0))
        end_raw = plan.get("end_time")
        end_t = (
            _parse_hh_mm_safe(end_raw, time(9, 0)) if end_raw else time(9, 0)
        )
        frequency = plan.get("frequency") or "daily"
        if frequency not in ("daily", "weekdays", "weekends"):
            frequency = "daily"

        telegram_id = callback.from_user.id

        try:
            async with get_db() as session:
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
                elif (
                    callback.from_user.username
                    and user.username != callback.from_user.username
                ):
                    user.username = callback.from_user.username

                habit = Habit(
                    user_id=user.id,
                    title=title,
                    start_time=start_t,
                    end_time=end_t,
                    frequency=frequency,
                )
                session.add(habit)
                await session.flush()

                today = date.today()
                task = Task(
                    user_id=user.id,
                    habit_id=habit.id,
                    title=title,
                    date=today,
                    start_time=start_t,
                    end_time=end_t,
                    is_completed=False,
                    is_placeholder=False,
                )
                session.add(task)

                stmt_ai = select(UserAIState).where(UserAIState.user_id == user.id)
                result_ai = await session.execute(stmt_ai)
                ai_state = result_ai.scalar_one_or_none()
                if ai_state is None:
                    ai_state = UserAIState(user_id=user.id, summary=plan)
                    session.add(ai_state)
                else:
                    ai_state.summary = plan
                    ai_state.updated_at = datetime.now(timezone.utc)

                await session.commit()

                logger.info(
                    "Created habit %d and task %d for user %d via AI multi-turn",
                    habit.id,
                    task.id,
                    user.id,
                )
        except Exception:
            logger.error(
                "Failed to create habit from AI plan for user %s",
                telegram_id,
                exc_info=True,
            )
            await callback.message.edit_text(
                "Не удалось сохранить привычку. Попробуйте позже или создайте вручную.",
                reply_markup=get_ai_fallback_keyboard(),
            )
            return

        await state.clear()
        await state.set_state(MainFSM.main_menu)
        time_line = f"{start_t.strftime('%H:%M')}–{end_t.strftime('%H:%M')}"
        await callback.message.edit_text(
            "✅ Привычка успешно создана!\n\n"
            f"*{title}*\n"
            f"Частота: {frequency}\n"
            f"Время: {time_line}",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data_cb == "assist:no":
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            "Хорошо, может быть, в другой раз!",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    # Unknown callback under confirm_plan — ignore safely
    logger.debug("Unhandled confirm_plan callback: %s", data_cb)
