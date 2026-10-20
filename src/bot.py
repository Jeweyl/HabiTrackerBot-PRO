"""Bot and Dispatcher instances for the Telegram bot application."""

import json
from datetime import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from src.config import settings


def _fsm_json_default(value: object) -> object:
    """Serialize values that commonly appear in FSM data but are not JSON-native."""
    if isinstance(value, time):
        return {"__habitracker_type__": "time", "value": value.isoformat()}
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _fsm_json_object_hook(value: dict[str, object]) -> object:
    """Restore values encoded by _fsm_json_default."""
    if value.get("__habitracker_type__") == "time":
        raw = value.get("value")
        if isinstance(raw, str):
            return time.fromisoformat(raw)
    return value


def _fsm_json_dumps(value: object) -> str:
    """JSON encoder used by aiogram RedisStorage for FSM data."""
    return json.dumps(value, default=_fsm_json_default)


def _fsm_json_loads(value: str) -> object:
    """JSON decoder used by aiogram RedisStorage for FSM data."""
    return json.loads(value, object_hook=_fsm_json_object_hook)


bot = Bot(
    token=settings.BOT_TOKEN,
    session=AiohttpSession(timeout=settings.BOT_HTTP_TIMEOUT),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
"""Bot instance configured with the token from application settings."""

redis = Redis.from_url(settings.REDIS_URL)
"""Async Redis client used for FSM storage."""

storage = RedisStorage(
    redis=redis,
    json_dumps=_fsm_json_dumps,
    json_loads=_fsm_json_loads,
)
"""Redis-backed FSM storage for multi-instance and restart-safe state."""

dp = Dispatcher(storage=storage)
"""Dispatcher instance with Redis FSM storage."""
