"""AI assistant handlers: multi-turn one-off task wizard via OpenRouter (B4).

Flow:
  entry (date default today) → title → AI turn (ask_questions | propose_task)
  → user answers (max 3 clarifying rounds) → soft plan preview → confirm
  → create ONE Task with habit_id=None (never creates Habit).

No task is written to the DB until the user confirms the preview.
Conflict check uses is_time_slot_free; force-add reuses ConflictFSM with
``ai_task_apply`` flag so manual task handlers are not confused.
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Any

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import Habit, Task, User
from src.db.session import get_db
from src.i18n import normalize_lang, t
from src.keyboards.inline import (
    get_ai_task_choice_keyboard,
    get_ai_task_fallback_keyboard,
    get_ai_task_plan_confirm_keyboard,
    get_conflict_resolution_keyboard,
    get_hour_selection_keyboard,
    get_main_menu_keyboard,
    get_minute_selection_keyboard,
)

from src.services.ai_apply import apply_propose_task_plan, resolve_task_plan
from src.services.ai_normalize import normalize_plan_times
from src.services.ai_schema import (

    AskQuestions,
    ClarifyingQuestion,
    ProposeTaskPlan,
    normalize_question,
)
from src.services.ai_service import (
    MAX_CLARIFYING_ROUNDS,
    build_multiturn_task_prompt,
    build_user_context_summary,
    send_to_ai_parsed,
)
from src.states.fsm import AITaskAssistantFSM, ConflictFSM, MainFSM
from src.utils.time_picker import PENDING_HOUR_KEY, parse_time_callback
from src.utils.timezone import local_now

logger = logging.getLogger(__name__)

router = Router()
"""Router for AI one-off task assistant handlers (B4)."""


# ---------------------------------------------------------------------------
# Helpers: main menu / bot-chat / deliver
# ---------------------------------------------------------------------------


async def _return_to_main_menu(
    event: Message | CallbackQuery, state: FSMContext, lang: str = "ru"
) -> None:
    """Clear FSM state and show the main menu."""
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    text = t("main.menu", lang)
    markup = get_main_menu_keyboard(lang)
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
                "Could not edit AI task waiting placeholder; sending a new message",
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
                "Could not delete AI task waiting placeholder after fallback send",
                exc_info=True,
            )


async def _show_waiting(
    event: Message | CallbackQuery,
    lang: str = "ru",
) -> Message | None:
    """Show the AI waiting indicator; never raise to the caller."""
    waiting = t("task_ai.waiting", lang)
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        try:
            return await event.message.edit_text(waiting)
        except Exception:
            logger.warning(
                "Could not edit message to AI task waiting text; sending new",
                exc_info=True,
            )
            try:
                return await event.message.answer(waiting)
            except Exception:
                logger.warning(
                    "Could not send AI task waiting placeholder",
                    exc_info=True,
                )
                return None
    try:
        return await event.answer(waiting)
    except Exception:
        logger.warning(
            "Could not send AI task waiting placeholder",
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Context loading
# ---------------------------------------------------------------------------


async def _load_user_ai_context(telegram_id: int) -> dict[str, Any]:
    """Load language, timezone and habits/tasks summary for the AI prompt.

    Never raises. Missing user → safe defaults.
    """
    language = "ru"
    tz = "UTC"
    habits: list[Any] = []
    tasks: list[Any] = []
    today_local = date.today()

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
                    "today_local": today_local,
                }

            language = normalize_lang(user.language)
            tz = user.timezone or "UTC"
            try:
                today_local = local_now(tz).date()
            except Exception:
                today_local = date.today()

            h_stmt = select(Habit).where(Habit.user_id == user.id)
            h_result = await session.execute(h_stmt)
            habits = list(h_result.scalars().all())

            t_stmt = (
                select(Task)
                .where(Task.user_id == user.id, Task.date == today_local)
                .order_by(Task.start_time)
            )
            t_result = await session.execute(t_stmt)
            tasks = list(t_result.scalars().all())
    except Exception:
        logger.warning(
            "Failed to load AI task user context for telegram_id=%s",
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
        "today_local": today_local,
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


def _task_skip_keyboard(lang: str = "ru"):
    """Skip/back/cancel using ``assist_task:`` namespace (not habit ``assist:``)."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from src.utils.keyboard_width import finalize_markup

    builder = InlineKeyboardBuilder()
    builder.button(text=t("task_ai.skip", lang), callback_data="assist_task:skip")
    builder.button(text=t("common.back", lang), callback_data="nav:back")
    builder.button(text=t("common.cancel", lang), callback_data="nav:cancel")
    builder.adjust(1, 2)
    return finalize_markup(builder)



def _keyboard_for_question(q: dict[str, Any], lang: str = "ru"):
    """Return inline keyboard for a stored question dict (task namespace)."""
    kind = q.get("kind") or "text"
    if kind == "choice":
        options = q.get("options") or []
        if options:
            return get_ai_task_choice_keyboard(list(options), lang=lang)
        return _task_skip_keyboard(lang)
    if kind == "time":
        return get_hour_selection_keyboard()
    return _task_skip_keyboard(lang)



def _format_question_text(
    q: dict[str, Any], context: str | None = None, lang: str = "ru"
) -> str:
    """Build message body for a clarifying question."""
    parts: list[str] = []
    if context:
        parts.append(str(context).strip())
    text = (q.get("text") or "").strip() or t("task_ai.clarify_fallback", lang)
    parts.append(text)
    kind = q.get("kind") or "text"
    if kind == "text":
        parts.append(t("task_ai.clarify_text_hint", lang))
    elif kind == "time":
        parts.append(t("task_ai.clarify_time_hint", lang))
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
    lang = data.get("language") or "ru"

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
    await state.set_state(AITaskAssistantFSM.clarifying)

    text = _format_question_text(current, context=context, lang=lang)
    markup = _keyboard_for_question(current, lang=lang)

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


def _format_task_plan_preview(
    plan: ProposeTaskPlan | dict[str, Any],
    *,
    default_date: str | None = None,
    lang: str = "ru",
    warnings: list[str] | None = None,
) -> str:
    """Soft preview text for a ProposeTaskPlan (no DB write).

    B5: *plan* should already be normalized; *warnings* list corrections.
    """
    if isinstance(plan, ProposeTaskPlan):
        data = plan.model_dump()
    else:
        data = plan

    title = data.get("title") or "—"
    task_date = data.get("date") or default_date or "—"
    start = data.get("start_time") or "—"
    end = data.get("end_time")
    duration = data.get("duration_minutes")
    comment = data.get("comment") or "—"

    time_line = f"{start}" + (f"–{end}" if end else "")
    duration_line = (
        t("common.minutes", lang, n=duration) if duration is not None else "—"
    )

    body = t(
        "task_ai.preview",
        lang,
        title=title,
        date=task_date,
        time=time_line,
        duration=duration_line,
        comment=comment,
    )
    if warnings:
        details = "; ".join(warnings)
        warn = t("task_ai.time_corrected_warning", lang, details=details)
        # Insert warning before the final confirm question line
        body = body.rstrip() + f"\n\n{warn}"
    return body



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
    """Call AI with task multiturn prompt and branch on AskQuestions / ProposeTaskPlan."""
    data = await state.get_data()
    task_title = data.get("title") or ""
    answers = data.get("answers") or {}
    language = data.get("language") or "ru"
    tz = data.get("timezone") or "UTC"
    summary = data.get("habits_tasks_summary") or ""
    clarifying_round = int(data.get("clarifying_round") or 0)
    default_date = data.get("task_date") or ""

    if placeholder is None:
        placeholder = await _show_waiting(event, lang=language)

    if clarifying_round >= MAX_CLARIFYING_ROUNDS:
        force_propose = True

    prompt = build_multiturn_task_prompt(
        task_title=task_title,
        answers=answers,
        language=language,
        timezone=tz,
        habits_tasks_summary=summary,
        default_date=str(default_date or ""),
        clarifying_round=clarifying_round,
        force_propose=force_propose,
    )

    try:
        ai_response = await send_to_ai_parsed(prompt)
    except Exception:
        logger.error("send_to_ai_parsed raised unexpectedly (task AI)", exc_info=True)
        ai_response = None

    if ai_response is None:
        await _deliver_ai_result(
            placeholder,
            event,
            t("task_ai.unavailable", language),
            reply_markup=get_ai_task_fallback_keyboard(language),
        )
        return

    if isinstance(ai_response, AskQuestions):
        if force_propose or clarifying_round >= MAX_CLARIFYING_ROUNDS:
            logger.info(
                "Task AI returned ask_questions at/after max rounds "
                "(round=%s); force-proposing",
                clarifying_round,
            )
            prompt2 = build_multiturn_task_prompt(
                task_title=task_title,
                answers=answers,
                language=language,
                timezone=tz,
                habits_tasks_summary=summary,
                default_date=str(default_date or ""),
                clarifying_round=clarifying_round,
                force_propose=True,
            )
            try:
                ai_response = await send_to_ai_parsed(prompt2)
            except Exception:
                logger.error(
                    "force propose task send_to_ai_parsed raised",
                    exc_info=True,
                )
                ai_response = None

            if ai_response is None or isinstance(ai_response, AskQuestions):
                await _deliver_ai_result(
                    placeholder,
                    event,
                    t("task_ai.unavailable", language),
                    reply_markup=get_ai_task_fallback_keyboard(language),
                )
                return
            # fall through to ProposeTaskPlan handling below
        else:
            questions = list(ai_response.questions or [])
            if not questions:
                await _deliver_ai_result(
                    placeholder,
                    event,
                    t("task_ai.unavailable", language),
                    reply_markup=get_ai_task_fallback_keyboard(language),
                )
                return

            pending = [_question_to_dict(q) for q in questions]
            pending = [q for q in pending if q.get("text")]
            if not pending:
                await _deliver_ai_result(
                    placeholder,
                    event,
                    t("task_ai.unavailable", language),
                    reply_markup=get_ai_task_fallback_keyboard(language),
                )
                return

            await state.update_data(
                clarifying_round=clarifying_round + 1,
                pending_questions=pending,
                ask_context=ai_response.context,
                current_question=None,
            )
            await _present_next_question(event, state, placeholder=placeholder)
            return

    if isinstance(ai_response, ProposeTaskPlan):
        # B5: normalize times before preview/FSM so confirm applies final times
        norm = normalize_plan_times(ai_response, kind="task")
        if not norm.ok or not norm.plan:
            logger.warning(
                "AI ProposeTaskPlan failed normalize: %s", norm.error
            )
            await _deliver_ai_result(
                placeholder,
                event,
                t("task_ai.unavailable", language),
                reply_markup=get_ai_task_fallback_keyboard(language),
            )
            return
        plan_data = norm.plan
        await state.update_data(
            proposed_plan=plan_data,
            pending_questions=[],
            current_question=None,
        )
        await state.set_state(AITaskAssistantFSM.confirm_plan)
        await _deliver_ai_result(
            placeholder,
            event,
            _format_task_plan_preview(
                plan_data,
                default_date=str(default_date or ""),
                lang=language,
                warnings=norm.warnings,
            ),
            reply_markup=get_ai_task_plan_confirm_keyboard(language),
            parse_mode="HTML",
        )
        return


    # Unexpected type (e.g. ProposePlan habit) — treat as unavailable
    await _deliver_ai_result(
        placeholder,
        event,
        t("task_ai.unavailable", language),
        reply_markup=get_ai_task_fallback_keyboard(language),
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


@router.callback_query(AITaskAssistantFSM.start, F.data == "nav:cancel")
@router.callback_query(AITaskAssistantFSM.clarifying, F.data == "nav:cancel")
@router.callback_query(AITaskAssistantFSM.confirm_plan, F.data == "nav:cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the AI task wizard and return to the main menu."""
    data = await state.get_data()
    lang = data.get("language") or "ru"
    await _return_to_main_menu(callback, state, lang=lang)
    logger.debug("AI task assistant cancelled by user %d", callback.from_user.id)


@router.callback_query(AITaskAssistantFSM.clarifying, F.data == "nav:back")
@router.callback_query(AITaskAssistantFSM.confirm_plan, F.data == "nav:back")
async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    """From clarifying/confirm → re-prompt title."""
    await callback.answer()
    data = await state.get_data()
    lang = data.get("language") or "ru"
    await state.set_state(AITaskAssistantFSM.start)
    await callback.message.edit_text(t("task_ai.prompt_title", lang))


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "new_task:ai")
async def ai_task_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry: start AI task wizard with default date = local today."""
    await callback.answer()
    ctx = await _load_user_ai_context(callback.from_user.id)
    today = ctx.get("today_local") or date.today()
    if not isinstance(today, date):
        today = date.today()

    await state.clear()
    await state.set_state(AITaskAssistantFSM.start)
    await state.update_data(
        task_date=today.isoformat(),
        language=ctx["language"],
        timezone=ctx["timezone"],
        habits_tasks_summary=ctx["habits_tasks_summary"],
        answers={},
        clarifying_round=0,
        pending_questions=[],
        current_question=None,
        proposed_plan=None,
    )
    await callback.message.edit_text(
        t("task_ai.prompt_title", ctx["language"]),
    )


@router.callback_query(F.data.startswith("task:ai:"))
async def ai_task_start_with_date(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry from calendar day: AI task with fixed date."""
    await callback.answer()
    raw = (callback.data or "").split(":", 2)
    iso = raw[2] if len(raw) > 2 else ""
    try:
        selected = date.fromisoformat(iso)
    except ValueError:
        selected = None

    ctx = await _load_user_ai_context(callback.from_user.id)
    if selected is None:
        selected = ctx.get("today_local") or date.today()
        if not isinstance(selected, date):
            selected = date.today()

    await state.clear()
    await state.set_state(AITaskAssistantFSM.start)
    await state.update_data(
        task_date=selected.isoformat(),
        language=ctx["language"],
        timezone=ctx["timezone"],
        habits_tasks_summary=ctx["habits_tasks_summary"],
        answers={},
        clarifying_round=0,
        pending_questions=[],
        current_question=None,
        proposed_plan=None,
    )
    await callback.message.edit_text(
        t("task_ai.prompt_title_dated", ctx["language"], date=selected.isoformat()),
    )


# ---------------------------------------------------------------------------
# State: start — receive task title → first AI turn
# ---------------------------------------------------------------------------


@router.message(AITaskAssistantFSM.start)
async def process_title(message: Message, state: FSMContext) -> None:
    """Validate title, ensure context, run first AI turn."""
    title = (message.text or "").strip()
    data = await state.get_data()
    lang = data.get("language") or "ru"

    if not title:
        await message.answer(t("task_ai.title_empty", lang))
        return

    if len(title) > 200:
        await message.answer(t("task_ai.title_too_long", lang))
        return

    # Refresh context if missing (e.g. after back)
    if not data.get("habits_tasks_summary"):
        ctx = await _load_user_ai_context(message.from_user.id)
        today = ctx.get("today_local") or date.today()
        if not isinstance(today, date):
            today = date.today()
        await state.update_data(
            language=ctx["language"],
            timezone=ctx["timezone"],
            habits_tasks_summary=ctx["habits_tasks_summary"],
            task_date=data.get("task_date") or today.isoformat(),
        )
        lang = ctx["language"]

    await state.update_data(
        title=title,
        answers={},
        clarifying_round=0,
        pending_questions=[],
        current_question=None,
        proposed_plan=None,
    )
    await _run_ai_turn(message, state)


# ---------------------------------------------------------------------------
# State: clarifying — text / choice / skip / time
# ---------------------------------------------------------------------------


@router.callback_query(AITaskAssistantFSM.clarifying, F.data == "assist_task:skip")
async def process_clarifying_skip(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Skip the current clarifying question."""
    await callback.answer()
    await _record_answer_and_continue(callback, state, "Пропущено")


@router.callback_query(
    AITaskAssistantFSM.clarifying, F.data.startswith("assist_task:choice:")
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


@router.callback_query(AITaskAssistantFSM.clarifying, F.data.startswith("time:"))
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

    try:
        await callback.answer()
    except Exception:
        pass


@router.message(AITaskAssistantFSM.clarifying)
async def process_clarifying_text(message: Message, state: FSMContext) -> None:
    """Handle free-text answer for the current clarifying question."""
    text = (message.text or "").strip()
    await _record_answer_and_continue(message, state, text if text else "Пропущено")


# ---------------------------------------------------------------------------
# Confirm / apply
# ---------------------------------------------------------------------------


async def _ensure_user_for_apply(
    session,
    telegram_id: int,
    username: str | None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    """Load or create the User row for AI task apply (flush only, no commit)."""
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language="ru",
            timezone="UTC",
        )
        session.add(user)
        await session.flush()
    else:
        if username and user.username != username:
            user.username = username
        if first_name is not None and user.first_name != first_name:
            user.first_name = first_name
        if last_name is not None and user.last_name != last_name:
            user.last_name = last_name
    return user



def _default_date_from_fsm(fsm_data: dict[str, Any]) -> date:
    """Parse task_date from FSM or fall back to today."""
    from datetime import datetime as _dt

    raw = fsm_data.get("task_date")
    if isinstance(raw, date) and not isinstance(raw, _dt):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            pass
    return date.today()



async def _apply_confirmed_task_plan(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    force: bool = False,
) -> None:
    """Resolve + apply proposed task plan; show conflict UI or success/error."""
    fsm_data = await state.get_data()
    plan = fsm_data.get("proposed_plan")
    fallback_title = fsm_data.get("title")
    lang = fsm_data.get("language") or "ru"
    telegram_id = callback.from_user.id
    default_date = _default_date_from_fsm(fsm_data)

    resolved = resolve_task_plan(
        plan,
        fallback_title=fallback_title,
        default_date=default_date,
    )
    if resolved is None:
        await callback.message.edit_text(
            t("task_ai.invalid_plan", lang),
            reply_markup=get_ai_task_fallback_keyboard(lang),
        )
        return

    try:
        async with get_db() as session:
            user = await _ensure_user_for_apply(
                session,
                telegram_id,
                callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
            )

            result = await apply_propose_task_plan(
                session,
                user,
                plan,
                force=force,
                fallback_title=fallback_title,
                default_date=default_date,
            )

            if result.status == "conflict":
                await state.update_data(
                    task_title=resolved.title,
                    task_date=resolved.task_date.isoformat(),
                    task_start_time=resolved.start_time.isoformat(timespec="minutes"),
                    task_end_time=(
                        resolved.end_time.isoformat(timespec="minutes")
                        if resolved.end_time
                        else None
                    ),
                    ai_task_apply=True,
                    proposed_plan=plan,
                    title=fallback_title or resolved.title,
                    language=lang,
                )
                await state.set_state(ConflictFSM.choose_action)
                await callback.message.edit_text(
                    t(
                        "task_ai.conflict",
                        lang,
                        title=resolved.title,
                        date=resolved.task_date.isoformat(),
                        time=(
                            f"{resolved.start_time.strftime('%H:%M')}"
                            + (
                                f"–{resolved.end_time.strftime('%H:%M')}"
                                if resolved.end_time
                                else ""
                            )
                        ),
                    ),
                    reply_markup=get_conflict_resolution_keyboard(),
                )
                return

            if result.status != "ok" or result.task is None:
                await callback.message.edit_text(
                    result.error or t("task_ai.save_failed", lang),
                    reply_markup=get_ai_task_fallback_keyboard(lang),
                )
                return

            task = result.task
    except Exception:
        logger.error(
            "Failed to apply AI task plan for user %s",
            telegram_id,
            exc_info=True,
        )
        await callback.message.edit_text(
            t("task_ai.save_failed", lang),
            reply_markup=get_ai_task_fallback_keyboard(lang),
        )
        return

    await state.clear()
    await state.set_state(MainFSM.main_menu)
    time_line = resolved.start_time.strftime("%H:%M")
    if resolved.end_time is not None:
        time_line = (
            f"{resolved.start_time.strftime('%H:%M')}–"
            f"{resolved.end_time.strftime('%H:%M')}"
        )
    await callback.message.edit_text(
        t(
            "task_ai.created",
            lang,
            title=resolved.title,
            date=resolved.task_date.isoformat(),
            time=time_line,
        ),
        reply_markup=get_main_menu_keyboard(lang),
        parse_mode="HTML",
    )
    logger.info(
        "AI task apply: task %s for telegram_id=%s force=%s habit_id=%s",
        getattr(task, "id", None),
        telegram_id,
        force,
        getattr(task, "habit_id", None),
    )


@router.callback_query(AITaskAssistantFSM.confirm_plan, F.data == "assist_task:yes")
async def process_plan_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm preview: apply one-off task."""
    await callback.answer()
    await _apply_confirmed_task_plan(callback, state, force=False)


@router.callback_query(AITaskAssistantFSM.confirm_plan, F.data == "assist_task:no")
async def process_plan_no(callback: CallbackQuery, state: FSMContext) -> None:
    """Decline preview: no DB write."""
    await callback.answer()
    data = await state.get_data()
    lang = data.get("language") or "ru"
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        t("task_ai.declined", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


@router.callback_query(
    ConflictFSM.choose_action,
    F.data == "conflict:force_add",
)
async def ai_task_conflict_force_add(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Force-add after AI task conflict when ``ai_task_apply`` flag is set.

    Manual task force_add is handled in ``tasks.py``; this handler only
    runs when the conflict originated from the AI task confirm path.
    Registered before tasks router force_add via main.py include order
    (ai_task after tasks) — uses SkipHandler when not AI path so tasks
    router can handle it if this runs first... Actually tasks is first.
    We rely on tasks force_add checking nothing; so we handle AI path
    only when flag set, else SkipHandler for safety if order changes.
    """
    data = await state.get_data()
    if not data.get("ai_task_apply"):
        raise SkipHandler()

    await callback.answer()

    if not data.get("proposed_plan"):
        title = data.get("task_title") or data.get("title")
        start = data.get("task_start_time")
        end = data.get("task_end_time")
        task_date = data.get("task_date")
        if start is not None:
            await state.update_data(
                proposed_plan={
                    "type": "propose_task",
                    "title": title,
                    "date": task_date,
                    "start_time": start
                    if isinstance(start, str)
                    else (
                        start.strftime("%H:%M")
                        if hasattr(start, "strftime")
                        else start
                    ),
                    "end_time": (
                        None
                        if end is None
                        else (
                            end
                            if isinstance(end, str)
                            else (
                                end.strftime("%H:%M")
                                if hasattr(end, "strftime")
                                else end
                            )
                        )
                    ),
                    "duration_minutes": None,
                    "comment": "",
                }
            )
    await _apply_confirmed_task_plan(callback, state, force=True)
