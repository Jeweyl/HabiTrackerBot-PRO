"""FastAPI application factory for the stats + account API."""


from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from src.api.routes import auth as auth_routes
from src.api.routes import habits as habits_routes
from src.api.routes import health as health_routes
from src.api.routes import me as me_routes
from src.api.routes import stats as stats_routes
from src.api.routes import tasks as tasks_routes



from src.api.token_store import MemoryTokenStore, RedisTokenStore, TokenStore
from src.config import settings


def _parse_cors_origins(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw or raw == "*":
        return ["*"]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _build_token_store() -> tuple[TokenStore, Redis | None]:
    """Prefer Redis; fall back to memory if Redis URL is unusable in tests."""
    try:
        redis = Redis.from_url(settings.REDIS_URL)
        return RedisTokenStore(redis), redis
    except Exception:
        return MemoryTokenStore(), None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bind token store (and optional Redis client) for the app lifetime."""
    store = getattr(app.state, "token_store", None)
    redis_client: Redis | None = getattr(app.state, "redis", None)

    if store is None:
        store, redis_client = _build_token_store()
        app.state.token_store = store
        app.state.redis = redis_client

    try:
        yield
    finally:
        redis_client = getattr(app.state, "redis", None)
        if redis_client is not None:
            await redis_client.aclose()


def create_app(
    *,
    token_store: TokenStore | None = None,
) -> FastAPI:
    """Create and configure the stats API application.

    Args:
        token_store: Optional pre-built store (tests inject MemoryTokenStore).
    """
    app = FastAPI(
        title="HabiTracker API",
        version="1.1.0",
        lifespan=lifespan,
    )


    if token_store is not None:
        app.state.token_store = token_store
        app.state.redis = None

    origins = _parse_cors_origins(settings.API_CORS_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False if origins == ["*"] else True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(me_routes.router)
    app.include_router(tasks_routes.router)
    app.include_router(habits_routes.router)
    app.include_router(stats_routes.router)
    return app





# ASGI entry for uvicorn: ``uvicorn src.api.app:app``
app = create_app()
