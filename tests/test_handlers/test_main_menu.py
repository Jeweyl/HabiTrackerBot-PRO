"""Tests for main menu inline button callbacks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.keyboards.inline import MAIN_MENU_BUTTONS

if TYPE_CHECKING:
    from tests.conftest import TestClient


@pytest.mark.asyncio
async def test_main_menu_button_returns_placeholder(
    client: "TestClient",
) -> None:
    """Verify that each main menu button returns the correct placeholder message."""

    for label, callback_data in MAIN_MENU_BUTTONS:
        message = await client.send_callback(callback_data)
        expected_text = (
            f"Функция '{label}' находится в разработке. Следите за обновлениями!"
        )
        assert message.text == expected_text, f"Unexpected text for {callback_data}"


@pytest.mark.asyncio
async def test_main_menu_callback_data_format(
    client: "TestClient",
) -> None:
    """Verify that all main menu callback_data values follow the expected format."""

    for _label, callback_data in MAIN_MENU_BUTTONS:
        assert callback_data.startswith(
            "main_menu:"
        ), f"Invalid prefix in {callback_data}"
        # Ensure there is a non-empty suffix after the prefix
        suffix = callback_data[len("main_menu:") :]
        assert suffix, f"Missing suffix in {callback_data}"


@pytest.mark.asyncio
async def test_main_menu_button_count(
    client: "TestClient",
) -> None:
    """Verify that the main menu has exactly 8 buttons."""

    assert (
        len(MAIN_MENU_BUTTONS) == 8
    ), f"Expected 8 main menu buttons, got {len(MAIN_MENU_BUTTONS)}"


@pytest.mark.asyncio
async def test_each_button_sends_response(
    client: "TestClient",
) -> None:
    """Verify that every main menu button triggers a non-empty response."""

    for _label, callback_data in MAIN_MENU_BUTTONS:
        message = await client.send_callback(callback_data)
        assert message.text is not None
        assert len(message.text) > 0
