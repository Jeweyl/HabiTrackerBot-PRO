"""Auth exchange and JWT edge-case tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import create_jwt, create_ott
from src.api.token_store import MemoryTokenStore
from tests.test_api.conftest import create_user


@pytest.mark.asyncio
async def test_exchange_invalid_ott_401(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    await create_user(api_session)
    resp = await client.post(
        "/api/v1/auth/exchange",
        json={"token": "not-a-real-token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_exchange_empty_body_422(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/exchange", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exchange_empty_token_422(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/exchange", json={"token": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exchange_valid_ott_returns_jwt(
    client: AsyncClient,
    api_session: AsyncSession,
    token_store: MemoryTokenStore,
) -> None:
    user = await create_user(api_session)
    ott = await create_ott(token_store, user.id)

    resp = await client.post(
        "/api/v1/auth/exchange",
        json={"token": ott},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert isinstance(data["access_token"], str)
    assert data["access_token"].count(".") == 2

    # One-shot: second use fails
    resp2 = await client.post(
        "/api/v1/auth/exchange",
        json={"token": ott},
    )
    assert resp2.status_code == 401


@pytest.mark.asyncio
async def test_stats_no_auth_401(client: AsyncClient) -> None:
    for path in (
        "/api/v1/stats/overview",
        "/api/v1/stats/daily?from=2026-01-01&to=2026-01-03",
        "/api/v1/stats/schedule?from=2026-01-01&to=2026-01-03",
    ):
        resp = await client.get(path)
        assert resp.status_code == 401, path


@pytest.mark.asyncio
async def test_stats_invalid_token_401(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/stats/overview",
        headers={"Authorization": "Bearer totally.invalid.token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stats_expired_jwt_401(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    user = await create_user(api_session)
    token = create_jwt(user.id, expire_minutes=-1)
    resp = await client.get(
        "/api/v1/stats/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stats_deleted_user_401(
    client: AsyncClient,
    api_session: AsyncSession,
) -> None:
    """JWT for non-existent user id → 401 (not empty stats)."""
    token = create_jwt(user_id=999999)
    resp = await client.get(
        "/api/v1/stats/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
