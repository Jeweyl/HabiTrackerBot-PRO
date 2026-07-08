"""Statistics handler for the Telegram bot."""

import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from src.db.models import Habit, Task, User
from src.db.session import get_db

logger = logging.getLogger(__name__)

router = Router()
"""Router for statistics handler."""


async def _calculate_streak(
    session,
    user_id: int,
    today: date,
    days: int = 7,
) -> int:
    """Calculate the current streak of consecutive days with all tasks completed.

    Goes backwards from today. A day counts as "fully completed" if there is
    at least one task scheduled on that day and all tasks on that day are
    completed.

    Args:
        session: An active SQLAlchemy async session.
        user_id: Internal user ID.
        today: Today's date.
        days: Maximum number of days to look back.

    Returns:
        The number of consecutive days (including today) where all tasks
        were completed.
    """
    streak = 0
    for offset in range(days):
        check_date = today - timedelta(days=offset)
        # Total tasks on this day
        total_stmt = select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.date == check_date,
        )
        total_result = await session.execute(total_stmt)
        total = total_result.scalar() or 0

        if total == 0:
            # No tasks on this day — break or continue?
            # A day with no tasks neither extends nor breaks the streak
            # (we only break on a day that HAS tasks and is not fully done)
            continue

        completed_stmt = select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.date == check_date,
            Task.is_completed.is_(True),
        )
        completed_result = await session.execute(completed_stmt)
        completed = completed_result.scalar() or 0

        if completed == total:
            streak += 1
        else:
            break  # streak broken

    return streak


@router.callback_query(F.data == "main_menu:statistics")
async def show_statistics(callback: CallbackQuery) -> None:
    """Show user statistics for the last 7 days.

    Displays:
        - Completed vs total tasks (count + percentage).
        - Missed tasks count.
        - Current streak of consecutive fully-completed days.
        - Total number of habits.

    If no data is available, shows an appropriate message.

    Args:
        callback: Incoming callback query from the main menu button.
    """
    await callback.answer()

    today = date.today()
    since = today - timedelta(days=6)

    async with get_db() as session:
        # Resolve user
        stmt = select(User).where(User.telegram_id == callback.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            await callback.message.edit_text(
                "⚠️ Пользователь не найден. Используйте /start для регистрации.",
            )
            return

        # Total tasks in the last 7 days
        total_stmt = select(func.count(Task.id)).where(
            Task.user_id == user.id,
            Task.date >= since,
            Task.date <= today,
        )
        total_result = await session.execute(total_stmt)
        total_count = total_result.scalar() or 0

        # Completed tasks in the last 7 days
        completed_stmt = select(func.count(Task.id)).where(
            Task.user_id == user.id,
            Task.date >= since,
            Task.date <= today,
            Task.is_completed.is_(True),
        )
        completed_result = await session.execute(completed_stmt)
        completed_count = completed_result.scalar() or 0

        # Missed tasks = total - completed (within the range)
        missed_count = total_count - completed_count

        # Total habits
        habits_stmt = select(func.count(Habit.id)).where(
            Habit.user_id == user.id,
        )
        habits_result = await session.execute(habits_stmt)
        habits_count = habits_result.scalar() or 0

        # Calculate streak
        streak = await _calculate_streak(session, user.id, today)

    if total_count == 0 and habits_count == 0:
        message = (
            "📊 <b>Статистика</b>\n\n"
            "У вас пока нет задач и привычек.\n"
            "Создайте первую привычку или задачу, "
            "чтобы начать отслеживать прогресс! 🚀"
        )
    elif total_count == 0:
        percentage = 0
        message = (
            "📊 <b>Ваша статистика за последние 7 дней:</b>\n\n"
            f"✅ Выполнено: 0 из 0 задач (0%)\n"
            f"📅 Пропущено: 0 задач\n"
            f"📋 Всего привычек: {habits_count}\n\n"
            "Задач за этот период нет. Добавьте задачи, "
            "чтобы увидеть прогресс!"
        )
    else:
        percentage = round(completed_count / total_count * 100)

        message = (
            "📊 <b>Ваша статистика за последние 7 дней:</b>\n\n"
            f"✅ Выполнено: {completed_count} из {total_count} задач ({percentage}%)\n"
            f"📅 Пропущено: {missed_count} задач\n"
            f"📋 Всего привычек: {habits_count}\n"
        )
        if streak > 0:
            message += f"🔥 Текущая серия: {streak} дн. подряд\n"
        else:
            message += "🔥 Текущая серия: 0 дн.\n"

        message += "\nПродолжайте в том же духе! 💪"

    await callback.message.edit_text(message, parse_mode="HTML")
