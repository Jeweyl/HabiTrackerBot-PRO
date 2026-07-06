"""Tests for database operations using the User model."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User


@pytest.mark.asyncio
async def test_create_and_read_user(async_session: AsyncSession) -> None:
    """Test creating a User record and reading it back from the database.

    Verifies that:
        - A User can be persisted.
        - The auto-generated id is assigned.
        - All fields are stored and retrieved correctly.
        - Default values for language and timezone are applied.
    """
    user = User(
        telegram_id=123456789,
        language="en",
        timezone="Europe/Moscow",
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)

    assert user.id is not None
    assert user.telegram_id == 123456789
    assert user.language == "en"
    assert user.timezone == "Europe/Moscow"
    assert user.created_at is not None
    assert user.updated_at is not None

    # Read back via query
    stmt = select(User).where(User.telegram_id == 123456789)
    result = await async_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.id == user.id
    assert fetched.language == "en"


@pytest.mark.asyncio
async def test_user_defaults(async_session: AsyncSession) -> None:
    """Test that default values are applied when optional fields are omitted.

    Verifies that:
        - language defaults to 'ru'.
        - timezone defaults to 'UTC'.
    """
    user = User(telegram_id=111222333)
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)

    assert user.language == "ru"
    assert user.timezone == "UTC"


@pytest.mark.asyncio
async def test_user_telegram_id_unique(async_session: AsyncSession) -> None:
    """Test that duplicate telegram_id raises an integrity error.

    Verifies that:
        - The unique constraint on telegram_id is enforced.
    """
    user1 = User(telegram_id=999888777)
    user2 = User(telegram_id=999888777)

    async_session.add(user1)
    await async_session.commit()

    async_session.add(user2)
    with pytest.raises(Exception):
        await async_session.commit()
    await async_session.rollback()