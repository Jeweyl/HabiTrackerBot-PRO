"""One-time token storage for dashboard auth exchange."""

from __future__ import annotations

import time
from typing import Protocol


class TokenStore(Protocol):
    """Minimal async key-value store for one-time tokens."""

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store *value* under *key* with TTL."""

    async def pop(self, key: str) -> str | None:
        """Atomically get-and-delete *key*; return None if missing/expired."""


class MemoryTokenStore:
    """In-process OTT store for tests and local dev without Redis."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        expires_at = time.monotonic() + max(1, int(ttl_seconds))
        self._data[key] = (value, expires_at)

    async def pop(self, key: str) -> str | None:
        item = self._data.pop(key, None)
        if item is None:
            return None
        value, expires_at = item
        if time.monotonic() > expires_at:
            return None
        return value


class RedisTokenStore:
    """Redis-backed OTT store for production API process."""

    def __init__(self, redis) -> None:
        self._redis = redis

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=max(1, int(ttl_seconds)))

    async def pop(self, key: str) -> str | None:
        # GETDEL when available; fallback GET+DEL for older Redis.
        try:
            value = await self._redis.getdel(key)
        except Exception:
            value = await self._redis.get(key)
            if value is not None:
                await self._redis.delete(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)
