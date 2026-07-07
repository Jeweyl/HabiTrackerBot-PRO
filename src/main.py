"""Application entry point — starts the Telegram bot with graceful shutdown."""

import asyncio
import logging
import signal

from src.bot import bot, dp
from src.handlers.common import router as common_router
from src.handlers.habits import router as habits_router

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure root logger with a standard format and INFO level."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def main() -> None:
    """Start the bot with polling and handle OS signals for graceful shutdown.

    Steps:
        1. Configure logging.
        2. Register handler routers on the dispatcher.
        3. Start polling in a background task.
        4. Wait for SIGINT or SIGTERM, then stop polling and close the bot session.
    """
    _setup_logging()

    dp.include_router(habits_router)  # Must be before common_router for priority
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

    await stop_event.wait()

    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
