"""Stats endpoints: overview, daily series, schedule."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_api.conftest import (
    auth_header_for,
    create_habit,
    create_task,
    create_user,
)


@pytest.mark.asyncio
async def test_overview_empty_user_zeros(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)

    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 0
    assert data["completed_tasks"] == 0
    assert data["missed_tasks"] == 0
    assert data["completion_rate"] == 0.0
    assert data["streak"] == 0
    assert data["habits_count"] == 0
    assert data["days"] == 7
    assert "from" in data and "to" in data


@pytest.mark.asyncio
async def test_daily_empty_series_filled(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    start = date(2026, 7, 1)
    end = date(2026, 7, 3)

    resp = await client.get(
        "/api/v1/stats/daily",
        params={"from": start.isoformat(), "to": end.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["from"] == "2026-07-01"
    assert data["to"] == "2026-07-03"
    assert len(data["series"]) == 3
    for point in data["series"]:
        assert point["total"] == 0
        assert point["completed"] == 0
        assert point["missed"] == 0


@pytest.mark.asyncio
async def test_schedule_empty_list(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)

    resp = await client.get(
        "/api/v1/stats/schedule",
        params={"from": "2026-07-01", "to": "2026-07-07"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []


@pytest.mark.asyncio
async def test_overview_with_tasks(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    today = date.today()
    yesterday = today - timedelta(days=1)

    await create_task(api_session, user, title="T1", task_date=today, is_completed=True)
    await create_task(api_session, user, title="T2", task_date=today, is_completed=True)
    await create_task(
        api_session, user, title="T3", task_date=yesterday, is_completed=False
    )
    await create_habit(api_session, user)

    headers = await auth_header_for(user)
    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 3
    assert data["completed_tasks"] == 2
    assert data["missed_tasks"] == 1
    assert data["completion_rate"] == 66.7
    assert data["habits_count"] == 1
    assert data["streak"] == 1  # today fully done; yesterday incomplete breaks further


@pytest.mark.asyncio
async def test_daily_with_partial_days(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    d1 = date(2026, 6, 1)
    d3 = date(2026, 6, 3)
    await create_task(api_session, user, title="A", task_date=d1, is_completed=True)
    await create_task(api_session, user, title="B", task_date=d1, is_completed=False)
    # d2 empty — gap-fill
    await create_task(api_session, user, title="C", task_date=d3, is_completed=True)

    headers = await auth_header_for(user)
    resp = await client.get(
        "/api/v1/stats/daily",
        params={"from": "2026-06-01", "to": "2026-06-03"},
        headers=headers,
    )
    assert resp.status_code == 200
    series = resp.json()["series"]
    assert len(series) == 3
    assert series[0] == {
        "date": "2026-06-01",
        "total": 2,
        "completed": 1,
        "missed": 1,
    }
    assert series[1] == {
        "date": "2026-06-02",
        "total": 0,
        "completed": 0,
        "missed": 0,
    }
    assert series[2] == {
        "date": "2026-06-03",
        "total": 1,
        "completed": 1,
        "missed": 0,
    }


@pytest.mark.asyncio
async def test_schedule_range_filter(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    await create_task(
        api_session,
        user,
        title="In range",
        task_date=date(2026, 5, 2),
        start_hour=10,
    )
    await create_task(
        api_session,
        user,
        title="Out of range",
        task_date=date(2026, 5, 10),
        start_hour=11,
    )

    headers = await auth_header_for(user)
    resp = await client.get(
        "/api/v1/stats/schedule",
        params={"from": "2026-05-01", "to": "2026-05-03"},
        headers=headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "In range"
    assert items[0]["start_time"] == "10:00"
    assert items[0]["end_time"] == "11:00"
    assert items[0]["is_completed"] is False
    assert items[0]["is_placeholder"] is False


@pytest.mark.asyncio
async def test_invalid_date_range_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)

    resp = await client.get(
        "/api/v1/stats/daily",
        params={"from": "2026-07-10", "to": "2026-07-01"},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_overview_days_out_of_range_422(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)

    resp = await client.get(
        "/api/v1/stats/overview",
        params={"days": 0},
        headers=headers,
    )
    assert resp.status_code == 422

    resp = await client.get(
        "/api/v1/stats/overview",
        params={"days": 91},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_placeholder_counted_like_bot(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    await create_task(
        api_session,
        user,
        title="Busy",
        is_placeholder=True,
        is_completed=False,
    )
    headers = await auth_header_for(user)
    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 1
    assert data["completed_tasks"] == 0


@pytest.mark.asyncio
async def test_habits_breakdown_empty(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.get("/api/v1/stats/habits", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["days"] == 7
    assert "from" in data and "to" in data


@pytest.mark.asyncio
async def test_habits_breakdown_with_data(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    habit_a = await create_habit(api_session, user, title="Run")
    habit_b = await create_habit(api_session, user, title="Read")
    today = date.today()

    await create_task(
        api_session,
        user,
        title="Run 1",
        task_date=today,
        is_completed=True,
        habit_id=habit_a.id,
    )
    await create_task(
        api_session,
        user,
        title="Run 2",
        task_date=today,
        is_completed=False,
        habit_id=habit_a.id,
    )
    # habit_b has no tasks in window — still listed with zeros

    headers = await auth_header_for(user)
    resp = await client.get(
        "/api/v1/stats/habits",
        params={"days": 7},
        headers=headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    by_title = {i["title"]: i for i in items}
    assert by_title["Run"]["total"] == 2
    assert by_title["Run"]["completed"] == 1
    assert by_title["Run"]["missed"] == 1
    assert by_title["Run"]["completion_rate"] == 50.0
    assert by_title["Read"]["total"] == 0
    assert by_title["Read"]["completed"] == 0
    assert by_title["Read"]["completion_rate"] == 0.0
    assert habit_b.id in {i["habit_id"] for i in items}


@pytest.mark.asyncio
async def test_habits_breakdown_days_out_of_range(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    headers = await auth_header_for(user)
    resp = await client.get(
        "/api/v1/stats/habits",
        params={"days": 0},
        headers=headers,
    )
    assert resp.status_code == 422
