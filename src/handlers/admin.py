"""Admin-only handlers for bot statistics and user listing."""

import logging

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


def _format_user_line(user: User) -> str:
    """Format a single user row for the admin report."""
    username = f"@{user.username}" if user.username else "—"
    return f"• `{user.telegram_id}` — {username}"


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Show total users and a list of telegram IDs with usernames.

    Access is restricted to ``settings.ADMIN_ID``.
    """
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    async with get_db() as session:
        total = await session.scalar(select(func.count()).select_from(User))
        result = await session.execute(
            select(User).order_by(User.created_at.desc(), User.id.desc())
        )
        users = result.scalars().all()

    if not users:
        await message.answer("👥 Пользователей пока нет.")
        return

    lines = [
        "👑 *Админ-панель*",
        f"Всего пользователей: *{total}*",
        "",
        "Список:",
    ]
    lines.extend(_format_user_line(user) for user in users)

    # Telegram message limit is 4096 chars; split if needed.
    chunk: list[str] = []
    chunk_len = 0
    for line in lines:
        line_len = len(line) + 1
        if chunk and chunk_len + line_len > 3500:
            await message.answer("\n".join(chunk), parse_mode="Markdown")
            chunk = [line]
            chunk_len = line_len
        else:
            chunk.append(line)
            chunk_len += line_len

    if chunk:
        await message.answer("\n".join(chunk), parse_mode="Markdown")

    logger.info(
        "Admin %s requested user list (%s users)",
        message.from_user.id,
        total,
    )
