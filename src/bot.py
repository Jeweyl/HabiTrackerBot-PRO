"""Bot and Dispatcher instances for the Telegram bot application."""

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.config import settings

bot = Bot(token=settings.BOT_TOKEN)
"""Bot instance configured with the token from application settings."""

storage = MemoryStorage()
"""In-memory FSM storage (will be replaced with RedisStorage later)."""

dp = Dispatcher(storage=storage)
"""Dispatcher instance with in-memory FSM storage."""
