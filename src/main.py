"""Application entry point — starts the Telegram bot with graceful shutdown."""

import asyncio
import logging
import signal

from src.bot import bot, dp, redis
from src.handlers.admin import router as admin_router
from src.handlers.ai_assistant import router as ai_assistant_router
from src.handlers.common import router as common_router
from src.handlers.habits import router as habits_router
from src.handlers.settings import router as settings_router
from src.handlers.statistics import router as statistics_router
from src.handlers.tasks import router as tasks_router
from src.services.reminder_service import process_reminders

logger = logging.getLogger(__name__)

REMINDER_POLL_SECONDS = 60
"""How often the reminder loop checks for due notifications."""


def _setup_logging() -> None:
    """Configure root logger with a standard format and INFO level."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def _reminder_loop(stop_event: asyncio.Event) -> None:
    """Periodically send due reminders until *stop_event* is set."""
    logger.info("Reminder loop started (interval=%ss)", REMINDER_POLL_SECONDS)
    while not stop_event.is_set():
        try:
            await process_reminders(bot)
        except Exception:
            logger.exception("Reminder loop iteration failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=REMINDER_POLL_SECONDS)
        except asyncio.TimeoutError:
            continue


async def main() -> None:
    """Start the bot with polling and handle OS signals for graceful shutdown.

    Steps:
        1. Configure logging.
        2. Register handler routers on the dispatcher.
        3. Start polling and the reminder loop in background tasks.
        4. Wait for SIGINT or SIGTERM, then stop tasks and close sessions.
    """
    _setup_logging()

    dp.include_router(admin_router)
    dp.include_router(tasks_router)  # Must be before habits_router for priority
    dp.include_router(habits_router)  # Must be before settings for priority
    dp.include_router(settings_router)  # Must be before statistics for priority
    dp.include_router(statistics_router)  # Must be before ai_assistant for priority
    dp.include_router(ai_assistant_router)  # Must be before common_router for priority
    dp.include_router(common_router)

    logger.info("Starting bot polling...")
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received, stopping bot...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows does not support add_signal_handler for SIGTERM
            signal.signal(sig, lambda *_: _signal_handler())

    polling_task = asyncio.create_task(dp.start_polling(bot))
    reminder_task = asyncio.create_task(_reminder_loop(stop_event))

    await stop_event.wait()

    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    try:
        await reminder_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()
    await redis.aclose()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
