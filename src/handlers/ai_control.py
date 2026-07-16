"""Free-form AI control: natural language → create/delete/complete/open menu."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.db.models import Task, User
from src.db.session import get_db
from src.handlers.common import main_menu_keyboard_for_telegram
from src.i18n import normalize_lang, t
from src.keyboards.inline import (
    get_control_choice_keyboard,
    get_control_confirm_keyboard,
    get_control_conflict_keyboard,
    get_control_pick_task_keyboard,
    get_control_skip_keyboard,
    get_hour_selection_keyboard,
    get_minute_selection_keyboard,
    get_month_calendar_keyboard,
    get_new_habit_choice_keyboard,
    get_new_task_choice_keyboard,
)
from src.services.ai_control_apply import (
    apply_control_complete_task,
    apply_control_create_task,
    apply_control_delete_task,
    format_task_label,
    match_control_task,
)
from src.services.ai_control_service import (
    MAX_CONTROL_CLARIFY_ROUNDS,
    build_control_context,
    build_control_prompt,
    send_control_to_ai,
)
from src.services.ai_schema import (
    AskQuestions,
    ClarifyingQuestion,
    ControlCompleteTask,
    ControlCreateTask,
    ControlDeleteTask,
    ControlListTasks,
    ControlMessage,
    ControlOpenMenu,
    normalize_question,
)

from src.states.fsm import (
    AIAssistantFSM,
    AIControlFSM,
    AITaskAssistantFSM,
    MainFSM,
    NewHabitFSM,
    NewTaskFSM,
)
from src.utils.time_picker import PENDING_HOUR_KEY, parse_time_callback
from src.utils.timezone import local_now

logger = logging.getLogger(__name__)

router = Router()
"""Router for free-form AI control (must be before common_router)."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_lang(telegram_id: int) -> str:
    async with get_db() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return "ru"
        return normalize_lang(user.language)

async def _load_control_context(telegram_id: int) -> dict[str, Any]:
    """Load user, local now, today's tasks, prompt context."""
    language = "ru"
    tz = "UTC"
    local_dt = datetime.now()
    tasks_today: list[Task] = []
    user: User | None = None

    try:
        async with get_db() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user is not None:
                language = normalize_lang(user.language)
                tz = user.timezone or "UTC"
                try:
                    local_dt = local_now(tz)
                except Exception:
                    local_dt = datetime.now()
                today = local_dt.date()
                t_result = await session.execute(
                    select(Task)
                    .where(
                        Task.user_id == user.id,
                        Task.date == today,
                        Task.is_placeholder.is_(False),
                    )
                    .order_by(Task.start_time.nulls_last(), Task.id)
                )
                tasks_today = list(t_result.scalars().all())
                # detach-friendly: copy light fields used in prompt only
    except Exception:
        logger.warning(
            "control context load failed telegram_id=%s",
            telegram_id,
            exc_info=True,
        )

    context_block = build_control_context(
        language=language,
        timezone=tz,
        local_now_dt=local_dt,
        tasks_today=tasks_today,
    )
    return {
        "language": language,
        "timezone": tz,
        "local_now": local_dt,
        "context_block": context_block,
        "user_id": user.id if user else None,
        "telegram_id": telegram_id,
    }

def _task_time_str(task: Task | None, lang: str) -> str:
    if task is None:
        return "—"
    if task.start_time is None:
        return t("control.untimed", lang)
    s = task.start_time.strftime("%H:%M")
    if task.end_time is not None:
        s = f"{s}–{task.end_time.strftime('%H:%M')}"
    return s

def _resolved_time_str(resolved, lang: str) -> str:
    if resolved is None or resolved.start_time is None:
        return t("control.untimed", lang)
    s = resolved.start_time.strftime("%H:%M")
    if resolved.end_time is not None:
        s = f"{s}–{resolved.end_time.strftime('%H:%M')}"
    return s

async def _reply(
    event: Message | CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = "HTML",
    placeholder: Message | None = None,
) -> None:
    """Send or edit a response for Message / CallbackQuery."""
    if placeholder is not None:
        try:
            await placeholder.edit_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode
            )
            return
        except Exception:
            pass

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode
            )
            return
        except Exception:
            await event.message.answer(
                text, reply_markup=reply_markup, parse_mode=parse_mode
            )
            return
    await event.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)

async def _return_main(event: Message | CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    markup = await main_menu_keyboard_for_telegram(event.from_user.id, lang)
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        try:
            await event.message.edit_text(t("main.menu", lang), reply_markup=markup)
        except Exception:
            await event.message.answer(t("main.menu", lang), reply_markup=markup)
    else:
        await event.answer(t("main.menu", lang), reply_markup=markup)

def _question_to_dict(q: ClarifyingQuestion | dict | str) -> dict[str, Any]:
    if isinstance(q, ClarifyingQuestion):
        return q.model_dump()
    normalized = normalize_question(q)
    if normalized is None:
        return {"text": str(q), "kind": "text", "options": None}
    return normalized.model_dump()

def _keyboard_for_question(q: dict[str, Any], lang: str):
    kind = q.get("kind") or "text"
    if kind == "choice":
        options = q.get("options") or []
        if options:
            return get_control_choice_keyboard(list(options), lang=lang)
        return get_control_skip_keyboard(lang)
    if kind == "time":
        return get_hour_selection_keyboard()
    return get_control_skip_keyboard(lang)

def _format_question_text(q: dict[str, Any], context: str | None, lang: str) -> str:
    parts: list[str] = []
    if context:
        parts.append(str(context).strip())
    text = (q.get("text") or "").strip() or t("control.clarify_fallback", lang)
    parts.append(text)
    kind = q.get("kind") or "text"
    if kind == "text":
        parts.append(t("control.clarify_text_hint", lang))
    elif kind == "time":
        parts.append(t("control.clarify_time_hint", lang))
    return "\n\n".join(p for p in parts if p)

# ---------------------------------------------------------------------------
# Intent dispatch
# ---------------------------------------------------------------------------

async def _show_day_schedule(
    event: Message | CallbackQuery,
    state: FSMContext,
    schedule_date: date,
    *,
    placeholder: Message | None = None,
) -> None:
    """Show tasks for *schedule_date*.

    Free-text entry cannot ``edit_text`` the user's message, so we always
    send a **new** bot message (``edit=False``). Optional waiting
    *placeholder* is deleted first.
    """
    from src.handlers.tasks import _show_schedule

    if placeholder is not None:
        try:
            await placeholder.delete()
        except Exception:
            pass

    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        # Prefer answering a new message so we never fail editing a stale UI.
        target_msg = event.message
    else:
        target_msg = event

    try:
        await _show_schedule(
            telegram_id=event.from_user.id,
            target=target_msg,
            schedule_date=schedule_date,
            state=state,
            edit=False,
        )
    except Exception:
        logger.exception(
            "Failed to show schedule for %s telegram_id=%s",
            schedule_date,
            event.from_user.id,
        )
        lang = await _get_user_lang(event.from_user.id)
        await _reply(
            event,
            t("control.unavailable", lang),
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
        )
        await state.set_state(MainFSM.main_menu)

async def _handle_list_tasks(
    event: Message | CallbackQuery,
    state: FSMContext,
    intent: ControlListTasks | dict[str, Any],
    lang: str,
    *,
    placeholder: Message | None = None,
) -> None:
    """Resolve date for list_tasks and show the day schedule."""
    if hasattr(intent, "model_dump"):
        data = intent.model_dump()  # type: ignore[union-attr]
    else:
        data = dict(intent)

    ctx = await _load_control_context(event.from_user.id)
    local_dt: datetime = ctx.get("local_now") or datetime.now()
    day = local_dt.date()

    raw_date = data.get("date")
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            day = date.fromisoformat(raw_date.strip())
        except ValueError:
            day = local_dt.date()

    await _show_day_schedule(
        event, state, day, placeholder=placeholder
    )

async def _handle_open_menu(
    event: Message | CallbackQuery,
    state: FSMContext,
    target: str,
    lang: str,
    *,
    placeholder: Message | None = None,
) -> None:
    """Navigate to an existing menu / wizard entry."""
    if target == "new_habit_choice":

        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("control.open_habit_choice", lang),
            reply_markup=get_new_habit_choice_keyboard(),
            placeholder=placeholder,
        )
        return
    if target == "new_habit_manual":
        await state.set_state(NewHabitFSM.title)
        await _reply(
            event,
            "✍️ Введите название привычки:" if lang == "ru" else "✍️ Enter habit title:",
            reply_markup=get_control_skip_keyboard(lang),
            placeholder=placeholder,
        )
        return
    if target == "new_habit_ai":
        await state.set_state(AIAssistantFSM.start)
        await _reply(
            event,
            "🤖 Опишите привычку, которую хотите сформировать:"
            if lang == "ru"
            else "🤖 Describe the habit you want to build:",
            reply_markup=get_control_skip_keyboard(lang),
            placeholder=placeholder,
        )
        return
    if target == "new_task":
        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("control.open_task_choice", lang),
            reply_markup=get_new_task_choice_keyboard(lang),
            placeholder=placeholder,
        )
        return
    if target == "new_task_ai":
        await state.set_state(AITaskAssistantFSM.start)
        await state.update_data(task_date=date.today().isoformat())
        await _reply(
            event,
            "🤖 Опишите задачу:" if lang == "ru" else "🤖 Describe the task:",
            reply_markup=get_control_skip_keyboard(lang),
            placeholder=placeholder,
        )
        return
    if target == "today":
        ctx = await _load_control_context(event.from_user.id)
        day = ctx["local_now"].date()
        await _show_day_schedule(
            event, state, day, placeholder=placeholder
        )
        return
    if target == "tomorrow":
        ctx = await _load_control_context(event.from_user.id)
        day = ctx["local_now"].date() + timedelta(days=1)
        await _show_day_schedule(
            event, state, day, placeholder=placeholder
        )
        return
    if target == "schedule":

        await state.update_data(view_mode=True)
        await state.set_state(NewTaskFSM.select_date)
        today = date.today()
        await _reply(
            event,
            "📅 Выберите дату:" if lang == "ru" else "📅 Pick a date:",
            reply_markup=get_month_calendar_keyboard(today.year, today.month),
            placeholder=placeholder,
        )
        return
    if target == "habits":
        from src.handlers.habits import _show_habit_list

        await state.clear()
        if placeholder is not None:
            try:
                await placeholder.delete()
            except Exception:
                pass
        target_msg = event.message if isinstance(event, CallbackQuery) else event
        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass
        await _show_habit_list(
            telegram_id=event.from_user.id,
            target=target_msg,
            state=state,
        )
        return
    if target == "settings":
        from src.handlers.settings import _render_settings_for_telegram_id

        await state.clear()
        await state.set_state(MainFSM.main_menu)
        text, markup, _lang = await _render_settings_for_telegram_id(
            event.from_user.id
        )
        await _reply(
            event,
            text,
            reply_markup=markup,
            placeholder=placeholder,
        )
        return
    if target == "stats":
        # Soft hand-off: show stats entry via main menu label + keyboard
        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("main.statistics", lang)
            + "\n\n"
            + (t("stats.title_empty", lang)),
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
            placeholder=placeholder,
        )
        return
    if target == "help":
        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("help.text", lang),
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
            placeholder=placeholder,
        )
        return

    await _reply(
        event,
        t("control.unavailable", lang),
        reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
        placeholder=placeholder,
    )
    await state.set_state(MainFSM.main_menu)

async def _apply_create(
    event: Message | CallbackQuery,
    state: FSMContext,
    intent: ControlCreateTask | dict[str, Any],
    lang: str,
    *,
    force: bool = False,
    placeholder: Message | None = None,
) -> None:
    async with get_db() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == event.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            await _reply(
                event,
                t("control.unavailable", lang),
                reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
                placeholder=placeholder,
            )
            return

        try:
            local_dt = local_now(user.timezone or "UTC")
        except Exception:
            local_dt = datetime.now()

        outcome = await apply_control_create_task(
            session,
            user,
            intent,
            force=force,
            local_now_dt=local_dt,
        )
        if outcome.status == "ok":
            await session.commit()
            task = outcome.task
            resolved = outcome.resolved
            await state.clear()
            await state.set_state(MainFSM.main_menu)
            await _reply(
                event,
                t(
                    "control.created",
                    lang,
                    title=(task.title if task else resolved.title if resolved else "—"),
                    date=(
                        task.date.isoformat()
                        if task
                        else resolved.task_date.isoformat()
                        if resolved
                        else "—"
                    ),
                    time=_task_time_str(task, lang)
                    if task
                    else _resolved_time_str(resolved, lang),
                ),
                reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
                placeholder=placeholder,
            )
            return

        if outcome.status == "conflict" and outcome.resolved is not None:
            await state.set_state(AIControlFSM.confirm)
            await state.update_data(
                pending_create=intent.model_dump()
                if hasattr(intent, "model_dump")
                else dict(intent),
                confirm_action="create_force",
                language=lang,
            )
            r = outcome.resolved
            await _reply(
                event,
                t(
                    "control.conflict",
                    lang,
                    title=r.title,
                    date=r.task_date.isoformat(),
                    time=_resolved_time_str(r, lang),
                ),
                reply_markup=get_control_conflict_keyboard(lang),
                placeholder=placeholder,
            )
            return

        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("control.unavailable", lang),
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
            placeholder=placeholder,
        )

async def _start_mutate_confirm(
    event: Message | CallbackQuery,
    state: FSMContext,
    *,
    action: str,
    task: Task,
    lang: str,
    placeholder: Message | None = None,
) -> None:
    await state.set_state(AIControlFSM.confirm)
    await state.update_data(
        confirm_action=action,
        confirm_task_id=task.id,
        language=lang,
    )
    key = "control.confirm_delete" if action == "delete" else "control.confirm_complete"
    await _reply(
        event,
        t(
            key,
            lang,
            title=task.title or "—",
            time=_task_time_str(task, lang),
        ),
        reply_markup=get_control_confirm_keyboard(
            action=action, task_id=task.id, lang=lang
        ),
        placeholder=placeholder,
    )

async def _handle_mutate_intent(
    event: Message | CallbackQuery,
    state: FSMContext,
    intent: ControlDeleteTask | ControlCompleteTask | dict[str, Any],
    *,
    action: str,
    lang: str,
    placeholder: Message | None = None,
) -> None:
    async with get_db() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == event.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            await _reply(
                event,
                t("control.unavailable", lang),
                reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
                placeholder=placeholder,
            )
            return
        try:
            local_dt = local_now(user.timezone or "UTC")
        except Exception:
            local_dt = datetime.now()

        match = await match_control_task(
            session, user, intent, local_now_dt=local_dt
        )

        if match.status == "found" and match.tasks:
            await _start_mutate_confirm(
                event,
                state,
                action=action,
                task=match.tasks[0],
                lang=lang,
                placeholder=placeholder,
            )
            return

        if match.status == "ambiguous" and match.tasks:
            await state.set_state(AIControlFSM.confirm)
            await state.update_data(confirm_action=action, language=lang)
            items = [
                (tk.id, format_task_label(tk, lang)) for tk in match.tasks
            ]
            await _reply(
                event,
                t("control.ambiguous", lang),
                reply_markup=get_control_pick_task_keyboard(
                    items, action=action, lang=lang
                ),
                placeholder=placeholder,
            )
            return

        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("control.not_found", lang),
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
            placeholder=placeholder,
        )

async def _dispatch_intent(
    event: Message | CallbackQuery,
    state: FSMContext,
    intent: Any,
    lang: str,
    *,
    placeholder: Message | None = None,
) -> None:
    if isinstance(intent, AskQuestions):
        questions = [
            _question_to_dict(q) for q in (intent.questions or [])
        ]
        questions = [q for q in questions if q]
        if not questions:
            await _reply(
                event,
                t("control.unavailable", lang),
                reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
                placeholder=placeholder,
            )
            await state.set_state(MainFSM.main_menu)
            return
        data = await state.get_data()
        round_n = int(data.get("clarifying_round") or 0) + 1
        await state.update_data(
            pending_questions=questions[1:],
            current_question=questions[0],
            ask_context=intent.context,
            clarifying_round=round_n,
            language=lang,
            **{PENDING_HOUR_KEY: None},
        )
        await state.set_state(AIControlFSM.clarifying)
        text = _format_question_text(
            questions[0], context=intent.context, lang=lang
        )
        markup = _keyboard_for_question(questions[0], lang)
        await _reply(event, text, reply_markup=markup, placeholder=placeholder)
        return

    if isinstance(intent, ControlCreateTask):
        await _apply_create(
            event, state, intent, lang, placeholder=placeholder
        )
        return

    if isinstance(intent, ControlDeleteTask):
        await _handle_mutate_intent(
            event,
            state,
            intent,
            action="delete",
            lang=lang,
            placeholder=placeholder,
        )
        return

    if isinstance(intent, ControlCompleteTask):
        await _handle_mutate_intent(
            event,
            state,
            intent,
            action="complete",
            lang=lang,
            placeholder=placeholder,
        )
        return

    if isinstance(intent, ControlListTasks):
        await _handle_list_tasks(
            event, state, intent, lang, placeholder=placeholder
        )
        return

    if isinstance(intent, ControlOpenMenu):
        await _handle_open_menu(
            event, state, intent.target, lang, placeholder=placeholder
        )
        return

    if isinstance(intent, ControlMessage):
        await state.clear()
        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            intent.text,
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
            placeholder=placeholder,
        )
        return

    await state.set_state(MainFSM.main_menu)
    await _reply(
        event,
        t("control.unavailable", lang),
        reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
        placeholder=placeholder,
    )

async def _run_control_turn(
    event: Message | CallbackQuery,
    state: FSMContext,
    *,
    user_text: str | None = None,
    placeholder: Message | None = None,
) -> None:
    data = await state.get_data()
    lang = data.get("language") or await _get_user_lang(event.from_user.id)
    ctx = await _load_control_context(event.from_user.id)
    lang = ctx["language"] or lang

    original = user_text or data.get("user_text") or ""
    answers = dict(data.get("answers") or {})
    round_n = int(data.get("clarifying_round") or 0)
    force = round_n >= MAX_CONTROL_CLARIFY_ROUNDS

    await state.update_data(
        user_text=original,
        language=lang,
        timezone=ctx["timezone"],
        answers=answers,
        clarifying_round=round_n,
    )

    prompt = build_control_prompt(
        user_text=original,
        language=lang,
        timezone=ctx["timezone"],
        local_now_dt=ctx["local_now"],
        context_block=ctx["context_block"],
        answers=answers,
        clarifying_round=round_n,
        force_action=force,
    )

    intent = await send_control_to_ai(prompt)
    if intent is None:
        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("control.unavailable", lang),
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
            placeholder=placeholder,
        )
        return

    # If model keeps asking past max rounds, force a soft message
    if isinstance(intent, AskQuestions) and force:
        await state.set_state(MainFSM.main_menu)
        await _reply(
            event,
            t("control.unavailable", lang),
            reply_markup=await main_menu_keyboard_for_telegram(event.from_user.id, lang),
            placeholder=placeholder,
        )
        return

    await _dispatch_intent(
        event, state, intent, lang, placeholder=placeholder
    )

# ---------------------------------------------------------------------------
# Entry: free text from main menu / idle
# ---------------------------------------------------------------------------

@router.message(StateFilter(MainFSM.main_menu), F.text, ~F.text.startswith("/"))
@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def control_free_text(message: Message, state: FSMContext) -> None:
    """Catch free-form text outside wizards and run AI control."""
    text = (message.text or "").strip()
    if not text:
        return
    # Persistent reply keyboard
    if text in {"🏠 Меню", "🏠 Menu", "Menu", "Меню"}:
        return

    lang = await _get_user_lang(message.from_user.id)
    await state.set_state(MainFSM.main_menu)
    await state.update_data(
        user_text=text,
        answers={},
        clarifying_round=0,
        language=lang,
        pending_questions=[],
        current_question=None,
    )

    placeholder: Message | None = None
    try:
        placeholder = await message.answer(t("control.waiting", lang))
    except Exception:
        placeholder = None

    try:
        await _run_control_turn(
            message, state, user_text=text, placeholder=placeholder
        )
    except Exception:
        logger.exception("control_free_text failed")
        await _reply(
            message,
            t("control.unavailable", lang),
            reply_markup=await main_menu_keyboard_for_telegram(message.from_user.id, lang),
            placeholder=placeholder,
        )
        await state.set_state(MainFSM.main_menu)

# ---------------------------------------------------------------------------
# Clarifying answers
# ---------------------------------------------------------------------------

async def _record_answer_and_continue(
    event: Message | CallbackQuery,
    state: FSMContext,
    answer: str,
    *,
    placeholder: Message | None = None,
) -> None:
    data = await state.get_data()
    answers = dict(data.get("answers") or {})
    current = data.get("current_question") or {}
    q_text = (current.get("text") if isinstance(current, dict) else None) or "q"
    answers[str(q_text)[:80]] = answer
    pending = list(data.get("pending_questions") or [])
    await state.update_data(answers=answers, current_question=None)

    if pending:
        nxt = pending[0]
        rest = pending[1:]
        lang = data.get("language") or "ru"
        await state.update_data(
            pending_questions=rest,
            current_question=nxt,
            **{PENDING_HOUR_KEY: None},
        )
        await state.set_state(AIControlFSM.clarifying)
        text = _format_question_text(
            nxt, context=data.get("ask_context"), lang=lang
        )
        markup = _keyboard_for_question(nxt, lang)
        await _reply(event, text, reply_markup=markup, placeholder=placeholder)
        return

    # Next AI turn
    lang = data.get("language") or "ru"
    wait_msg = placeholder
    if wait_msg is None and isinstance(event, CallbackQuery):
        try:
            wait_msg = await event.message.edit_text(t("control.waiting", lang))
        except Exception:
            wait_msg = None
    elif wait_msg is None:
        try:
            wait_msg = await event.answer(t("control.waiting", lang))  # type: ignore[arg-type]
        except Exception:
            wait_msg = None
    await _run_control_turn(event, state, placeholder=wait_msg)

@router.callback_query(StateFilter(AIControlFSM.clarifying), F.data == "ctrl:skip")
async def control_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _record_answer_and_continue(callback, state, "Пропущено")

@router.callback_query(
    StateFilter(AIControlFSM.clarifying), F.data.startswith("ctrl:choice:")
)
async def control_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    current = data.get("current_question") or {}
    options = list((current.get("options") if isinstance(current, dict) else None) or [])
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        idx = -1
    answer = options[idx] if 0 <= idx < len(options) else (callback.data or "")
    await _record_answer_and_continue(callback, state, answer)

@router.callback_query(
    StateFilter(AIControlFSM.clarifying), F.data.startswith("time:")
)
async def control_time_pick(callback: CallbackQuery, state: FSMContext) -> None:
    """Reuse shared time picker callbacks during control clarifying."""
    await callback.answer()
    data = await state.get_data()
    current = data.get("current_question") or {}
    if not isinstance(current, dict) or (current.get("kind") or "text") != "time":
        return

    kind, payload = parse_time_callback(callback.data or "")
    lang = data.get("language") or "ru"

    if kind == "hour":
        hour = int(payload)  # type: ignore[arg-type]
        await state.update_data(**{PENDING_HOUR_KEY: hour})
        await callback.message.edit_text(
            f"⏰ {hour:02d}:xx",
            reply_markup=get_minute_selection_keyboard(hour),
        )
        return

    if kind == "final":
        start_time = payload  # datetime.time
        answer = start_time.strftime("%H:%M")  # type: ignore[union-attr]
        await _record_answer_and_continue(callback, state, answer)
        return

    if kind == "null":
        await _record_answer_and_continue(callback, state, "Пропущено")
        return

    await callback.message.edit_text(
        t("control.clarify_time_hint", lang),
        reply_markup=get_hour_selection_keyboard(),
    )

@router.message(StateFilter(AIControlFSM.clarifying), F.text)
async def control_clarify_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    await _record_answer_and_continue(message, state, text)

# ---------------------------------------------------------------------------
# Confirm delete / complete / force create
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(AIControlFSM.confirm), F.data == "ctrl:no")
async def control_confirm_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    lang = (await state.get_data()).get("language") or await _get_user_lang(
        callback.from_user.id
    )
    await state.clear()
    await state.set_state(MainFSM.main_menu)
    await callback.message.edit_text(
        t("control.cancelled", lang),
        reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
    )

@router.callback_query(
    StateFilter(AIControlFSM.confirm), F.data.startswith("ctrl:yes:")
)
async def control_confirm_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = (callback.data or "").split(":")
    # ctrl:yes:{action}:{task_id}
    action = parts[2] if len(parts) >= 4 else ""
    try:
        task_id = int(parts[3]) if len(parts) >= 4 else 0
    except ValueError:
        task_id = 0
    lang = (await state.get_data()).get("language") or await _get_user_lang(
        callback.from_user.id
    )

    if not task_id or action not in {"delete", "complete"}:
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            t("control.unavailable", lang),
            reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
        )
        return

    async with get_db() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            await callback.message.edit_text(
                t("control.unavailable", lang),
                reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
            )
            return
        if action == "delete":
            outcome = await apply_control_delete_task(session, user, task_id)
            await session.commit()
            msg_key = "control.deleted"
        else:
            outcome = await apply_control_complete_task(session, user, task_id)
            await session.commit()
            msg_key = "control.completed"

    await state.clear()
    await state.set_state(MainFSM.main_menu)
    if outcome.status == "ok" and outcome.task is not None:
        await callback.message.edit_text(
            t(msg_key, lang, title=outcome.task.title or "—"),
            reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            t("control.not_found", lang),
            reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
        )

@router.callback_query(
    StateFilter(AIControlFSM.confirm), F.data.startswith("ctrl:pick:")
)
async def control_pick_task(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = (callback.data or "").split(":")
    # ctrl:pick:{action}:{task_id}
    action = parts[2] if len(parts) >= 4 else ""
    try:
        task_id = int(parts[3]) if len(parts) >= 4 else 0
    except ValueError:
        task_id = 0
    lang = (await state.get_data()).get("language") or await _get_user_lang(
        callback.from_user.id
    )
    if not task_id or action not in {"delete", "complete"}:
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            t("control.unavailable", lang),
            reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
        )
        return

    async with get_db() as session:
        result = await session.execute(
            select(Task).where(
                Task.id == task_id,
            )
        )
        task = result.scalar_one_or_none()
        # ownership check
        if task is not None:
            u = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = u.scalar_one_or_none()
            if user is None or task.user_id != user.id:
                task = None

    if task is None:
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            t("control.not_found", lang),
            reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
        )
        return

    await _start_mutate_confirm(
        callback, state, action=action, task=task, lang=lang
    )

@router.callback_query(StateFilter(AIControlFSM.confirm), F.data == "ctrl:force_add")
async def control_force_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    lang = data.get("language") or await _get_user_lang(callback.from_user.id)
    pending = data.get("pending_create")
    if not pending:
        await state.set_state(MainFSM.main_menu)
        await callback.message.edit_text(
            t("control.cancelled", lang),
            reply_markup=await main_menu_keyboard_for_telegram(callback.from_user.id, lang),
        )
        return
    await _apply_create(
        callback, state, pending, lang, force=True, placeholder=callback.message
    )
