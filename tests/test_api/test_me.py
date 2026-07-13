"""Account profile GET/PATCH /api/v1/me tests."""

from __future__ import annotations

from datetime import time as dtime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_api.conftest import auth_header_for, create_user


@pytest.mark.asyncio
async def test_me_no_auth_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_get_ok(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session, language="en")
    user.username = "demo"
    user.first_name = "Ada"
    user.timezone = "+3"
    user.reminder_time = dtime(9, 0)
    user.check_interval = 30
    await api_session.commit()

    headers = await auth_header_for(user)
    resp = await client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user.id
    assert data["telegram_id"] == user.telegram_id
    assert data["username"] == "demo"
    assert data["first_name"] == "Ada"
    assert data["language"] == "en"
    assert data["timezone"] == "+3"
    assert data["reminder_time"] == "09:00"
    assert data["check_interval"] == 30


@pytest.mark.asyncio
async def test_me_patch_language_and_interval(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session, language="ru")
    headers = await auth_header_for(user)

    resp = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={"language": "en", "check_interval": 45},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "en"
    assert data["check_interval"] == 45

    await api_session.refresh(user)
    assert user.language == "en"
    assert user.check_interval == 45


@pytest.mark.asyncio
async def test_me_patch_timezone_and_reminder(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)

    resp = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={"timezone": "+3", "reminder_time": "08:00"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["timezone"] == "+3"
    assert data["reminder_time"] == "08:00"

    await api_session.refresh(user)
    assert user.timezone == "+3"
    assert user.reminder_time == dtime(8, 0)


@pytest.mark.asyncio
async def test_me_patch_reminder_off(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    user.reminder_time = dtime(10, 0)
    await api_session.commit()
    headers = await auth_header_for(user)

    resp = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={"reminder_time": None},
    )
    assert resp.status_code == 200
    assert resp.json()["reminder_time"] is None

    await api_session.refresh(user)
    assert user.reminder_time is None


@pytest.mark.asyncio
async def test_me_patch_omit_leaves_reminder(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    user.reminder_time = dtime(11, 0)
    await api_session.commit()
    headers = await auth_header_for(user)

    resp = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={"language": "en"},
    )
    assert resp.status_code == 200
    assert resp.json()["reminder_time"] == "11:00"
    await api_session.refresh(user)
    assert user.reminder_time == dtime(11, 0)


@pytest.mark.asyncio
async def test_me_patch_bad_language_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={"language": "de"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_me_patch_bad_interval_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={"check_interval": 7},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_me_patch_bad_timezone_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={"timezone": "Europe/Moscow"},
    )
    assert resp.status_code == 422
