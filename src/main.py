"""Application entry point — verifies infrastructure readiness."""

import asyncio
import logging

from sqlalchemy import text

from src.db.session import async_engine

logger = logging.getLogger(__name__)


async def check_database_connection() -> bool:
    """Verify database connectivity by executing a lightweight query.

    Returns:
        True if the connection is successful and ``SELECT 1`` returns the
        expected result.
    """
    async with async_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        row = result.scalar()
        return row == 1


async def main() -> None:
    """Run the infrastructure readiness check.

    Steps:
        1. Initialize logging.
        2. Check database connection via ``SELECT 1``.
        3. Print success message and exit.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Checking database connection...")

    connected = await check_database_connection()
    if not connected:
        logger.error("Database connection check returned unexpected result.")
        raise SystemExit(1)

    print("🚀 Bot infrastructure ready! Database connected.")

    # Dispose the engine pool before exiting
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())