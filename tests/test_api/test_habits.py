"""Habit CRUD API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_api.conftest import auth_header_for, create_habit, create_user


@pytest.mark.asyncio
async def test_habits_no_auth_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/habits")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_list_and_get_habit(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)

    resp = await client.post(
        "/api/v1/habits",
        headers=headers,
        json={
            "title": "Morning run",
            "start_time": "07:00",
            "end_time": "07:30",
            "frequency": "weekdays",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Morning run"
    assert data["start_time"] == "07:00"
    assert data["end_time"] == "07:30"
    assert data["frequency"] == "weekdays"
    habit_id = data["id"]

    listed = await client.get("/api/v1/habits", headers=headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(i["id"] == habit_id for i in items)

    one = await client.get(f"/api/v1/habits/{habit_id}", headers=headers)
    assert one.status_code == 200
    assert one.json()["title"] == "Morning run"


@pytest.mark.asyncio
async def test_create_habit_conflict_409(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    await create_habit(api_session, user, title="Existing")
    headers = await auth_header_for(user)

    resp = await client.post(
        "/api/v1/habits",
        headers=headers,
        json={
            "title": "Overlap",
            "start_time": "09:00",
            "end_time": "10:00",
            "frequency": "daily",
        },
    )
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["code"] == "habit_conflict"


@pytest.mark.asyncio
async def test_patch_and_delete_habit(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    habit = await create_habit(api_session, user, title="Old")
    habit_id = habit.id
    headers = await auth_header_for(user)

    resp = await client.patch(
        f"/api/v1/habits/{habit_id}",
        headers=headers,
        json={
            "title": "New title",
            "start_time": "11:00",
            "end_time": "12:00",
            "frequency": "weekends",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "New title"
    assert data["start_time"] == "11:00"
    assert data["frequency"] == "weekends"

    deleted = await client.delete(f"/api/v1/habits/{habit_id}", headers=headers)
    assert deleted.status_code == 204

    missing = await client.get(f"/api/v1/habits/{habit_id}", headers=headers)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_habit_ownership(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    owner = await create_user(api_session, telegram_id=111)
    other = await create_user(api_session, telegram_id=222)
    habit = await create_habit(api_session, owner)
    habit_id = habit.id
    other_headers = await auth_header_for(other)

    resp = await client.patch(
        f"/api/v1/habits/{habit_id}",
        headers=other_headers,
        json={"title": "Hack"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bad_frequency_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.post(
        "/api/v1/habits",
        headers=headers,
        json={
            "title": "Bad",
            "start_time": "09:00",
            "end_time": "10:00",
            "frequency": "monthly",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bad_grid_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.post(
        "/api/v1/habits",
        headers=headers,
        json={
            "title": "Bad",
            "start_time": "09:10",
            "end_time": "10:00",
            "frequency": "daily",
        },
    )
    assert resp.status_code == 422
