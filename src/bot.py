"""Bot and Dispatcher instances for the Telegram bot application."""

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from src.config import settings

bot = Bot(token=settings.BOT_TOKEN)
"""Bot instance configured with the token from application settings."""

redis = Redis.from_url(settings.REDIS_URL)
"""Async Redis client used for FSM storage."""

storage = RedisStorage(redis=redis)
"""Redis-backed FSM storage for multi-instance and restart-safe state."""

dp = Dispatcher(storage=storage)
"""Dispatcher instance with Redis FSM storage."""
