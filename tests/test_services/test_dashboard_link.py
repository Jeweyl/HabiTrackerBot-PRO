"""Tests for dashboard one-time login link builder."""

from __future__ import annotations

import pytest

from src.api.token_store import MemoryTokenStore
from src.services.dashboard_link import (
    build_login_url,
    issue_dashboard_link,
    normalize_dashboard_base_url,
)


def test_normalize_empty_url_returns_none() -> None:
    assert normalize_dashboard_base_url("") is None
    assert normalize_dashboard_base_url("   ") is None
    assert normalize_dashboard_base_url(None) is None
    assert normalize_dashboard_base_url("none") is None


def test_normalize_strips_trailing_slash() -> None:
    assert (
        normalize_dashboard_base_url("http://localhost:8080/")
        == "http://localhost:8080"
    )
    assert (
        normalize_dashboard_base_url("https://dash.example.com")
        == "https://dash.example.com"
    )


def test_build_login_url_encodes_token() -> None:
    url = build_login_url("http://localhost:8080", "abc+/=xyz")
    assert url.startswith("http://localhost:8080/login?token=")
    assert "abc" in url
    assert "+" not in url.split("token=", 1)[1] or "%2B" in url


@pytest.mark.asyncio
async def test_issue_link_none_when_url_empty() -> None:
    store = MemoryTokenStore()
    link = await issue_dashboard_link(1, store, base_url="")
    assert link is None


@pytest.mark.asyncio
async def test_issue_link_none_when_url_whitespace() -> None:
    store = MemoryTokenStore()
    link = await issue_dashboard_link(1, store, base_url="  ")
    assert link is None


@pytest.mark.asyncio
async def test_issue_link_contains_token_and_login_path() -> None:
    store = MemoryTokenStore()
    link = await issue_dashboard_link(
        42,
        store,
        base_url="http://localhost:8080/",
    )
    assert link is not None
    assert link.startswith("http://localhost:8080/login?token=")
    token = link.split("token=", 1)[1]
    assert len(token) >= 16


@pytest.mark.asyncio
async def test_issue_link_invalid_user_id_returns_none() -> None:
    store = MemoryTokenStore()
    assert await issue_dashboard_link(0, store, base_url="http://x") is None
    assert await issue_dashboard_link(-1, store, base_url="http://x") is None


@pytest.mark.asyncio
async def test_issue_link_store_failure_returns_none() -> None:
    class BrokenStore:
        async def set(self, key: str, value: str, ttl_seconds: int) -> None:
            raise RuntimeError("redis down")

    link = await issue_dashboard_link(
        1,
        BrokenStore(),  # type: ignore[arg-type]
        base_url="http://localhost:8080",
    )
    assert link is None
