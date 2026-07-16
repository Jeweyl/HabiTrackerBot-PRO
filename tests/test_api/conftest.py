"""Fixtures for FastAPI stats API tests (SQLite + MemoryTokenStore)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date, time as dtime

import pytest_asyncio

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.app import create_app
from src.api.auth import create_jwt, create_ott
from src.api.deps import get_session
from src.api.token_store import MemoryTokenStore
from src.db.models import Base, Habit, Task, User


@pytest_asyncio.fixture
async def api_session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite session with full schema."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def token_store() -> MemoryTokenStore:
    return MemoryTokenStore()


@pytest_asyncio.fixture
async def api_app(api_session: AsyncSession, token_store: MemoryTokenStore):
    """FastAPI app with DB and token store overrides."""
    app = create_app(token_store=token_store)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield api_session
            await api_session.commit()
        except Exception:
            await api_session.rollback()
            raise

    app.dependency_overrides[get_session] = _override_session
    return app


@pytest_asyncio.fixture
async def client(api_app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def create_user(
    session: AsyncSession,
    *,
    telegram_id: int = 123456,
    language: str = "ru",
) -> User:
    user = User(telegram_id=telegram_id, language=language, timezone="UTC")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def create_task(
    session: AsyncSession,
    user: User,
    *,
    title: str = "Task",
    task_date: date | None = None,
    start_hour: int = 9,
    is_completed: bool = False,
    is_placeholder: bool = False,
    habit_id: int | None = None,
) -> Task:
    task = Task(
        user_id=user.id,
        habit_id=habit_id,
        title=title,
        date=task_date or date.today(),
        start_time=dtime(start_hour, 0),
        end_time=dtime(start_hour + 1, 0),
        is_completed=is_completed,
        is_placeholder=is_placeholder,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def create_habit(
    session: AsyncSession,
    user: User,
    *,
    title: str = "Habit",
) -> Habit:
    habit = Habit(
        user_id=user.id,
        title=title,
        start_time=dtime(9, 0),
        end_time=dtime(10, 0),
        frequency="daily",
    )
    session.add(habit)
    await session.commit()
    await session.refresh(habit)
    return habit


async def auth_header_for(
    user: User,
    token_store: MemoryTokenStore | None = None,
) -> dict[str, str]:
    """Return Authorization header with a valid JWT for *user*."""
    token = create_jwt(user.id, telegram_id=user.telegram_id)
    return {"Authorization": f"Bearer {token}"}


async def issue_ott(token_store: MemoryTokenStore, user: User) -> str:
    return await create_ott(token_store, user.id)
