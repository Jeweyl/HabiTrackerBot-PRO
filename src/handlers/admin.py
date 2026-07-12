"""Admin-only handlers for bot statistics and user listing."""

import html
import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from src.config import settings
from src.db.models import User
from src.db.session import get_db

logger = logging.getLogger(__name__)

router = Router()
"""Router for admin-only commands."""


def _is_admin(telegram_id: int) -> bool:
    """Return ``True`` if *telegram_id* matches the configured admin."""
    return telegram_id == settings.ADMIN_ID


def _display_name(user: User) -> str:
    """Build a human-readable display name from first/last name."""
    parts = [p for p in (user.first_name, user.last_name) if p]
    if not parts:
        return "—"
    return " ".join(parts)


def _format_last_seen(user: User) -> str:
    """Format last activity time (``updated_at``) for the admin list.

    Uses UTC wall-clock time. Falls back to ``created_at`` if needed.
    """
    ts = user.updated_at or user.created_at
    if ts is None:
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def _format_user_line(user: User) -> str:
    """Format a single user row for the admin report (HTML).

    Shows telegram id, @username (or —), display name, last activity,
    and a deep-link that may open the profile when the client knows the user.
    """
    username = f"@{user.username}" if user.username else "—"
    name = _display_name(user)
    last_seen = _format_last_seen(user)
    # Escape user-controlled text for HTML parse mode.
    safe_username = html.escape(username)
    safe_name = html.escape(name)
    safe_last_seen = html.escape(last_seen)
    link = f'<a href="tg://user?id={user.telegram_id}">открыть</a>'
    return (
        f"• <code>{user.telegram_id}</code> — {safe_username} "
        f"({safe_name}) · {safe_last_seen} {link}"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Show total users and a list of telegram IDs with usernames/names.

    Access is restricted to ``settings.ADMIN_ID``.
    """
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    async with get_db() as session:
        total = await session.scalar(select(func.count()).select_from(User))
        result = await session.execute(
            select(User).order_by(User.updated_at.desc(), User.id.desc())
        )
        users = result.scalars().all()

    if not users:
        await message.answer("👥 Пользователей пока нет.")
        return

    lines = [
        "👑 <b>Админ-панель</b>",
        f"Всего пользователей: <b>{total}</b>",
        "",
        "Список (id — @ник (имя) · последняя активность):",
        "<i>Ссылка tg://user открывает профиль не всегда — "
        "только если Telegram уже знает этого пользователя.</i>",
        "",
    ]
    lines.extend(_format_user_line(user) for user in users)

    # Telegram message limit is 4096 chars; split if needed.
    chunk: list[str] = []
    chunk_len = 0
    for line in lines:
        line_len = len(line) + 1
        if chunk and chunk_len + line_len > 3500:
            await message.answer("\n".join(chunk), parse_mode="HTML")
            chunk = [line]
            chunk_len = line_len
        else:
            chunk.append(line)
            chunk_len += line_len

    if chunk:
        await message.answer("\n".join(chunk), parse_mode="HTML")

    logger.info(
        "Admin %s requested user list (%s users)",
        message.from_user.id,
        total,
    )
