"""Statistics handler for the Telegram bot."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db

from src.i18n import normalize_lang, t
from src.services import stats_service
from src.services.stats_service import HabitBreakdownItem, OverviewStats
from src.utils.keyboard_width import finalize_markup


logger = logging.getLogger(__name__)

router = Router()
"""Router for statistics handler."""

ALLOWED_DAYS = frozenset({7, 30})


def _parse_days(raw: str | int | None, default: int = 7) -> int:
    """Return 7 or 30; anything else falls back to *default*."""
    try:
        days = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return days if days in ALLOWED_DAYS else default


async def _load_user(telegram_id: int) -> tuple[int | None, str]:
    """Load internal user id + language by telegram id.

    Returns ``(None, "ru")`` when the user is missing. Only primitive values
    are returned so callers never touch a detached ORM instance.
    """
    async with get_db() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None, "ru"
        return int(user.id), normalize_lang(user.language)



async def _issue_dashboard_url(user_id: int) -> str | None:
    """Create a one-time dashboard login URL, or None on config/store errors."""
    from src.services.dashboard_link import issue_bot_dashboard_url

    return await issue_bot_dashboard_url(user_id)



def _stats_keyboard(
    lang: str,
    *,
    days: int = 7,
    dashboard_url: str | None = None,
    view: str = "overview",
) -> InlineKeyboardMarkup:
    """Build statistics keyboard: period, views, dashboard, back."""
    builder = InlineKeyboardBuilder()
    days = _parse_days(days)

    builder.row(
        InlineKeyboardButton(
            text=t("stats.btn_7d_active" if days == 7 else "stats.btn_7d", lang),
            callback_data="stats:period:7",
        ),
        InlineKeyboardButton(
            text=t("stats.btn_30d_active" if days == 30 else "stats.btn_30d", lang),
            callback_data="stats:period:30",
        ),
    )

    builder.row(
        InlineKeyboardButton(
            text=t("stats.btn_habits", lang),
            callback_data=f"stats:habits:{days}",
        ),
        InlineKeyboardButton(
            text=t("stats.btn_daily", lang),
            callback_data=f"stats:daily:{days}",
        ),
    )

    if view != "overview":
        builder.row(
            InlineKeyboardButton(
                text=t("stats.btn_overview", lang),
                callback_data=f"stats:overview:{days}",
            )
        )

    if dashboard_url:
        # Open inside Telegram as a Mini App (not an external browser tab).
        builder.row(
            InlineKeyboardButton(
                text=t("stats.open_dashboard", lang),
                web_app=WebAppInfo(url=dashboard_url),
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=t("stats.refresh_link", lang),
                callback_data=f"stats:refresh_link:{days}",
            )
        )

    builder.row(
        InlineKeyboardButton(
            text=t("stats.back", lang),
            callback_data="nav:cancel",
        )
    )
    return finalize_markup(builder)


def _format_overview_message(
    overview: OverviewStats,
    lang: str,
    *,
    dashboard_available: bool,
) -> str:
    """Render overview text for the given stats window."""
    if overview.total_tasks == 0 and overview.habits_count == 0:
        text = (
            f"{t('stats.title_empty', lang)}\n\n"
            f"{t('stats.empty_all', lang)}"
        )
    elif overview.total_tasks == 0:
        text = (
            f"{t('stats.title', lang, days=overview.days)}\n\n"
            f"{t('stats.completed_line', lang, completed=0, total=0, rate=0)}\n"
            f"{t('stats.missed_line', lang, missed=0)}\n"
            f"{t('stats.habits_line', lang, count=overview.habits_count)}\n\n"
            f"{t('stats.empty_tasks', lang)}"
        )
    else:
        rate = int(round(overview.completion_rate))
        text = (
            f"{t('stats.title', lang, days=overview.days)}\n\n"
            f"{t('stats.completed_line', lang, completed=overview.completed_tasks, total=overview.total_tasks, rate=rate)}\n"
            f"{t('stats.missed_line', lang, missed=overview.missed_tasks)}\n"
            f"{t('stats.habits_line', lang, count=overview.habits_count)}\n"
        )
        if overview.streak > 0:
            text += f"{t('stats.streak_line', lang, streak=overview.streak)}\n"
        else:
            text += f"{t('stats.streak_zero', lang)}\n"
        text += f"\n{t('stats.keep_going', lang)}"

    if not dashboard_available:
        text += t("stats.dashboard_unavailable", lang)
    return text


def _format_habits_message(
    items: list[HabitBreakdownItem],
    days: int,
    lang: str,
) -> str:
    """Render per-habit breakdown."""
    lines = [t("stats.habits_title", lang, days=days), ""]
    if not items:
        lines.append(t("stats.habits_empty", lang))
        return "\n".join(lines)

    for item in items:
        rate = int(round(item.completion_rate))
        lines.append(
            t(
                "stats.habit_line",
                lang,
                title=item.title or f"#{item.habit_id}",
                completed=item.completed,
                total=item.total,
                rate=rate,
            )
        )
    return "\n".join(lines)


def _format_daily_message(
    series: list[stats_service.DailyPoint],
    days: int,
    lang: str,
) -> str:
    """Render compact per-day mini chart (newest first)."""
    lines = [t("stats.daily_title", lang, days=days), ""]
    # Show newest day first for quick scanning.
    for point in reversed(series):
        label = point.date.strftime("%m-%d")
        if point.total <= 0:
            lines.append(t("stats.daily_empty_day", lang, date=label))
        else:
            lines.append(
                t(
                    "stats.daily_line",
                    lang,
                    date=label,
                    completed=point.completed,
                    missed=point.missed,
                )
            )
    return "\n".join(lines)


async def _render_overview(
    callback: CallbackQuery,
    *,
    days: int,
    user_id: int,
    lang: str,
) -> None:
    """Load overview + dashboard link and edit the message."""
    days = _parse_days(days)
    async with get_db() as session:
        overview = await stats_service.get_overview(session, user_id, days=days)

    dashboard_url = await _issue_dashboard_url(user_id)
    text = _format_overview_message(
        overview,
        lang,
        dashboard_available=dashboard_url is not None,
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_stats_keyboard(
            lang,
            days=days,
            dashboard_url=dashboard_url,
            view="overview",
        ),
    )


async def _render_habits(
    callback: CallbackQuery,
    *,
    days: int,
    user_id: int,
    lang: str,
) -> None:
    """Load habit breakdown and edit the message."""
    days = _parse_days(days)
    async with get_db() as session:
        items = await stats_service.get_habit_breakdown(
            session, user_id, days=days
        )

    dashboard_url = await _issue_dashboard_url(user_id)
    text = _format_habits_message(items, days, lang)
    if dashboard_url is None:
        text += t("stats.dashboard_unavailable", lang)

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_stats_keyboard(
            lang,
            days=days,
            dashboard_url=dashboard_url,
            view="habits",
        ),
    )


async def _render_daily(
    callback: CallbackQuery,
    *,
    days: int,
    user_id: int,
    lang: str,
) -> None:
    """Load daily series mini-view and edit the message."""
    days = _parse_days(days)
    today = date.today()
    since = today - timedelta(days=days - 1)
    async with get_db() as session:
        series = await stats_service.get_daily_series(
            session, user_id, since, today
        )

    dashboard_url = await _issue_dashboard_url(user_id)
    text = _format_daily_message(series, days, lang)
    if dashboard_url is None:
        text += t("stats.dashboard_unavailable", lang)

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_stats_keyboard(
            lang,
            days=days,
            dashboard_url=dashboard_url,
            view="daily",
        ),
    )


@router.callback_query(F.data == "main_menu:statistics")
async def show_statistics(callback: CallbackQuery) -> None:
    """Show user statistics overview (default last 7 days)."""
    await callback.answer()
    user_id, lang = await _load_user(callback.from_user.id)
    if user_id is None:
        await callback.message.edit_text(t("common.user_not_found", lang))
        return
    await _render_overview(callback, days=7, user_id=user_id, lang=lang)


@router.callback_query(F.data.startswith("stats:period:"))
async def stats_period(callback: CallbackQuery) -> None:
    """Switch overview period between 7 and 30 days."""
    await callback.answer()
    parts = (callback.data or "").split(":")
    days = _parse_days(parts[2] if len(parts) > 2 else 7)
    user_id, lang = await _load_user(callback.from_user.id)
    if user_id is None:
        await callback.message.edit_text(t("common.user_not_found", lang))
        return
    await _render_overview(callback, days=days, user_id=user_id, lang=lang)


@router.callback_query(F.data.startswith("stats:overview:"))
async def stats_overview(callback: CallbackQuery) -> None:
    """Return to overview for the selected period."""
    await callback.answer()
    parts = (callback.data or "").split(":")
    days = _parse_days(parts[2] if len(parts) > 2 else 7)
    user_id, lang = await _load_user(callback.from_user.id)
    if user_id is None:
        await callback.message.edit_text(t("common.user_not_found", lang))
        return
    await _render_overview(callback, days=days, user_id=user_id, lang=lang)


@router.callback_query(F.data.startswith("stats:habits:"))
async def stats_habits(callback: CallbackQuery) -> None:
    """Show per-habit breakdown for the selected period."""
    await callback.answer()
    parts = (callback.data or "").split(":")
    days = _parse_days(parts[2] if len(parts) > 2 else 7)
    user_id, lang = await _load_user(callback.from_user.id)
    if user_id is None:
        await callback.message.edit_text(t("common.user_not_found", lang))
        return
    await _render_habits(callback, days=days, user_id=user_id, lang=lang)


@router.callback_query(F.data.startswith("stats:daily:"))
async def stats_daily(callback: CallbackQuery) -> None:
    """Show compact daily mini series for the selected period."""
    await callback.answer()
    parts = (callback.data or "").split(":")
    days = _parse_days(parts[2] if len(parts) > 2 else 7)
    user_id, lang = await _load_user(callback.from_user.id)
    if user_id is None:
        await callback.message.edit_text(t("common.user_not_found", lang))
        return
    await _render_daily(callback, days=days, user_id=user_id, lang=lang)


@router.callback_query(F.data.startswith("stats:refresh_link:"))
async def stats_refresh_link(callback: CallbackQuery) -> None:
    """Re-issue dashboard OTT and show overview with URL button if possible."""
    parts = (callback.data or "").split(":")
    days = _parse_days(parts[2] if len(parts) > 2 else 7)
    user_id, lang = await _load_user(callback.from_user.id)
    if user_id is None:
        await callback.answer()
        await callback.message.edit_text(t("common.user_not_found", lang))
        return

    dashboard_url = await _issue_dashboard_url(user_id)
    if dashboard_url is None:
        await callback.answer(t("stats.link_failed", lang), show_alert=True)
    else:
        await callback.answer(t("stats.link_issued", lang))

    async with get_db() as session:
        overview = await stats_service.get_overview(session, user_id, days=days)

    text = _format_overview_message(
        overview,
        lang,
        dashboard_available=dashboard_url is not None,
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_stats_keyboard(
            lang,
            days=days,
            dashboard_url=dashboard_url,
            view="overview",
        ),
    )


