"""Task CRUD API tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_api.conftest import auth_header_for, create_task, create_user


@pytest.mark.asyncio
async def test_tasks_no_auth_401(client: AsyncClient) -> None:
    today = date.today().isoformat()
    resp = await client.get(f"/api/v1/tasks?from={today}&to={today}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_and_list_task(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    day = date.today()

    resp = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Deep work",
            "date": day.isoformat(),
            "start_time": "09:00",
            "end_time": "10:00",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Deep work"
    assert data["start_time"] == "09:00"
    assert data["end_time"] == "10:00"
    assert data["is_completed"] is False
    task_id = data["id"]

    listed = await client.get(
        f"/api/v1/tasks?from={day.isoformat()}&to={day.isoformat()}",
        headers=headers,
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(i["id"] == task_id for i in items)


@pytest.mark.asyncio
async def test_create_conflict_409(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    day = date.today()
    await create_task(api_session, user, task_date=day, start_hour=9)
    headers = await auth_header_for(user)

    resp = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Overlap",
            "date": day.isoformat(),
            "start_time": "09:30",
            "end_time": "10:30",
        },
    )
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["code"] == "time_conflict"


@pytest.mark.asyncio
async def test_patch_complete_and_delete(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    task = await create_task(api_session, user)
    task_id = task.id
    headers = await auth_header_for(user)

    resp = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
        json={"is_completed": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_completed"] is True

    deleted = await client.delete(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
    )
    assert deleted.status_code == 204

    missing = await client.get(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_patch_schedule_and_ownership(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    owner = await create_user(api_session, telegram_id=111)
    other = await create_user(api_session, telegram_id=222)
    task = await create_task(api_session, owner, start_hour=14)
    task_id = task.id
    other_headers = await auth_header_for(other)
    owner_headers = await auth_header_for(owner)

    # Other user cannot see/edit
    resp = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=other_headers,
        json={"title": "Hack"},
    )
    assert resp.status_code == 404

    tomorrow = date.today() + timedelta(days=1)
    resp2 = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=owner_headers,
        json={
            "title": "Moved",
            "date": tomorrow.isoformat(),
            "start_time": "16:00",
            "end_time": "17:00",
        },
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["title"] == "Moved"
    assert data["date"] == tomorrow.isoformat()
    assert data["start_time"] == "16:00"


@pytest.mark.asyncio
async def test_bad_grid_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Bad",
            "date": date.today().isoformat(),
            "start_time": "09:10",
            "end_time": "10:00",
        },
    )
    assert resp.status_code == 422
