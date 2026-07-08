"""Tests for habit creation, listing, editing, and deletion handlers."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, User

if TYPE_CHECKING:
    from aiogram import Bot

    from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Fixture: a dispatcher with both habits and common routers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def full_dispatcher() -> Dispatcher:
    """Return a fresh Dispatcher with both habits and common routers."""
    import src.handlers.common  # noqa: F811
    import src.handlers.habits  # noqa: F811

    importlib.reload(src.handlers.habits)
    importlib.reload(src.handlers.common)
    from src.handlers.common import router as common_router  # noqa: F811
    from src.handlers.habits import router as habits_router  # noqa: F811

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(habits_router)
    dp.include_router(common_router)
    return dp


@pytest_asyncio.fixture(scope="function", autouse=True)
async def _patch_generator_db(
    monkeypatch,
    async_session: AsyncSession,
) -> None:
    """Redirect habit_generator.get_db to the in-memory test session."""

    @asynccontextmanager
    async def _fake_get_db():
        yield async_session

    import src.services.habit_generator as gen_module

    monkeypatch.setattr(gen_module, "get_db", _fake_get_db)


@pytest_asyncio.fixture(scope="function")
async def full_client(
    test_bot: Bot,
    full_dispatcher: Dispatcher,
) -> "TestClient":
    """Provide a TestClient wired to the full dispatcher (habits + common)."""
    from tests.conftest import TestClient

    return TestClient(bot=test_bot, dp=full_dispatcher)


# ---------------------------------------------------------------------------
# Helper: mock get_db with the test async_session
# ---------------------------------------------------------------------------


def _mock_get_db_context(async_session: AsyncSession):
    """Return a context manager factory that yields the test session."""

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    return _mock_get_db


# ---------------------------------------------------------------------------
# Helper: create a user and a habit in the test database
# ---------------------------------------------------------------------------


async def _create_user(async_session: AsyncSession, telegram_id: int = 123456) -> User:
    """Create and return a test User."""
    user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()
    return user


async def _create_habit(
    async_session: AsyncSession,
    user: User,
    title: str = "Тест",
    start_hour: int = 8,
    end_hour: int | None = 9,
    frequency: str = "daily",
) -> Habit:
    """Create and return a test Habit."""
    habit = Habit(
        user_id=user.id,
        title=title,
        start_time=time(start_hour, 0),
        end_time=time(end_hour, 0) if end_hour is not None else None,
        frequency=frequency,
    )
    async_session.add(habit)
    await async_session.commit()
    return habit


# ===================================================================
# Existing creation-wizard tests
# ===================================================================


@pytest.mark.asyncio
async def test_new_habit_start(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that clicking "➕ Создать привычку" starts the wizard."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        message = await full_client.send_callback("main_menu:new_habit")

    assert "Введите название привычки" in message.text


@pytest.mark.asyncio
async def test_full_wizard_flow(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify the complete happy path of the habit creation wizard."""
    user = await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        msg = await full_client.send_callback("main_menu:new_habit")
        assert "Введите название привычки" in msg.text

        msg = await full_client.send_message("Утренняя пробежка")
        assert "Выберите время начала" in msg.text

        msg = await full_client.send_callback("time:07:00")
        assert "Выберите время окончания" in msg.text

        msg = await full_client.send_callback("time:08:00")
        assert "Выберите периодичность" in msg.text

        msg = await full_client.send_callback("freq:daily")
        assert "Привычка успешно создана" in msg.text
        assert "Утренняя пробежка" in msg.text

    stmt = select(Habit).where(Habit.title == "Утренняя пробежка")
    result = await async_session.execute(stmt)
    habit = result.scalar_one()
    assert habit.user_id == user.id
    assert habit.start_time.strftime("%H:%M") == "07:00"
    assert habit.end_time.strftime("%H:%M") == "08:00"
    assert habit.frequency == "daily"


@pytest.mark.asyncio
async def test_cancel_during_wizard(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that cancelling the wizard clears state and shows the main menu."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Тестовая привычка")
        msg = await full_client.send_callback("nav:cancel")
        assert "Создание привычки отменено" in msg.text

    stmt = select(Habit).where(Habit.title == "Тестовая привычка")
    result = await async_session.execute(stmt)
    habits = result.scalars().all()
    assert len(habits) == 0


@pytest.mark.asyncio
async def test_empty_title_rejected(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that an empty or whitespace-only title is rejected."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        msg = await full_client.send_message("   ")
        assert "от 1 до 200 символов" in msg.text


@pytest.mark.asyncio
async def test_end_time_keyboard_filters_by_start_time(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify end_time keyboard filtering by start_time."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Чтение")
        msg = await full_client.send_callback("time:12:00")
        assert "Выберите время окончания" in msg.text

        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}

        assert "time:11:00" not in all_cb
        assert "time:12:00" not in all_cb
        assert "time:13:00" in all_cb
        assert "time:23:00" in all_cb
        assert "time:null" in all_cb
        assert "nav:back" in all_cb
        assert "nav:cancel" in all_cb


@pytest.mark.asyncio
async def test_habit_with_null_end_time(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that selecting ``time:null`` creates a habit with end_time=None."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Медитация")
        await full_client.send_callback("time:09:00")
        msg = await full_client.send_callback("time:null")
        assert "Выберите периодичность" in msg.text

        msg = await full_client.send_callback("freq:weekdays")
        assert "Медитация" in msg.text
        assert "без ограничения по времени" in msg.text

    stmt = select(Habit).where(Habit.title == "Медитация")
    result = await async_session.execute(stmt)
    habit = result.scalar_one()
    assert habit.end_time is None
    assert habit.frequency == "weekdays"


@pytest.mark.asyncio
async def test_end_time_not_greater_than_start_time_rejected(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that end_time ≤ start_time is rejected."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Йога")
        await full_client.send_callback("time:12:00")
        msg = await full_client.send_callback("time:10:00")
        assert "должно быть позже" in msg.text


@pytest.mark.asyncio
async def test_start_time_keyboard_has_no_null_option(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that the start_time keyboard does NOT include ``time:null``."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        msg = await full_client.send_message("Бег")
        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}
        assert "time:null" not in all_cb
        assert "nav:back" in all_cb
        assert "nav:cancel" in all_cb


# ===================================================================
# habit list — new two-level navigation
# ===================================================================


@pytest.mark.asyncio
async def test_show_empty_habit_list(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that an empty habit list shows a placeholder message."""
    await _create_user(async_session)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        msg = await full_client.send_callback("main_menu:habits")
        assert "У вас пока нет привычек" in msg.text
        assert msg.reply_markup is not None  # main menu


@pytest.mark.asyncio
async def test_show_habit_list_with_data(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that the habit list shows all habits with «Интерактировать» button."""
    user = await _create_user(async_session)
    await _create_habit(async_session, user, "Бег", 7, 8)
    await _create_habit(async_session, user, "Чтение", 21, 22, "weekdays")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        msg = await full_client.send_callback("main_menu:habits")
        assert "📋 Ваши привычки" in msg.text
        assert "Бег" in msg.text
        assert "Чтение" in msg.text

        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}
        assert "habits:interact" in all_cb
        assert "nav:cancel" in all_cb
        # No direct edit/delete buttons on this level
        assert not any(cb.startswith("habit:edit:") for cb in all_cb)
        assert not any(cb.startswith("habit:delete:") for cb in all_cb)


# ===================================================================
# Two-level navigation: interact menu
# ===================================================================


@pytest.mark.asyncio
async def test_interact_menu_shows_habit_buttons(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that «Интерактировать» opens a sub-menu with habit buttons."""
    user = await _create_user(async_session)
    habit1 = await _create_habit(async_session, user, "Бег", 7, 8)
    habit2 = await _create_habit(async_session, user, "Чтение", 21, 22, "weekdays")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        msg = await full_client.send_callback("habits:interact")

        assert "📋 Ваши привычки" in msg.text
        assert "Бег" in msg.text
        assert "Чтение" in msg.text

        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}
        assert f"habit:select:{habit1.id}" in all_cb
        assert f"habit:select:{habit2.id}" in all_cb
        assert "nav:back" in all_cb
        assert "nav:cancel" in all_cb

        # Verify button labels match habit titles
        all_labels = {btn.text for row in keyboard for btn in row}
        assert "Бег" in all_labels
        assert "Чтение" in all_labels
        assert "⬅️ Назад" in all_labels
        assert "❌ Отмена" in all_labels


@pytest.mark.asyncio
async def test_habit_select_shows_manage_menu(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that selecting a habit opens the manage menu (edit/delete)."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Бег", 7, 8)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        msg = await full_client.send_callback(f"habit:select:{habit.id}")

        assert "Бег" in msg.text
        assert "07:00" in msg.text
        assert "08:00" in msg.text
        assert "Выберите действие" in msg.text

        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}
        assert f"habit:edit:{habit.id}" in all_cb
        assert f"habit:delete:{habit.id}" in all_cb
        assert "nav:back" in all_cb
        assert "nav:cancel" in all_cb


# ===================================================================
# Back navigation tests
# ===================================================================


@pytest.mark.asyncio
async def test_back_from_interact_to_view_list(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that «Назад» from interact_list returns to view_list."""
    user = await _create_user(async_session)
    await _create_habit(async_session, user, "Бег", 7, 8)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        msg = await full_client.send_callback("nav:back")

        assert "📋 Ваши привычки" in msg.text
        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}
        assert "habits:interact" in all_cb
        assert "nav:cancel" in all_cb


@pytest.mark.asyncio
async def test_back_from_manage_to_interact(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that «Назад» from manage_single returns to interact_list."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Бег", 7, 8)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        msg = await full_client.send_callback("nav:back")

        assert "📋 Ваши привычки" in msg.text
        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}
        assert f"habit:select:{habit.id}" in all_cb
        assert "⬅️ Назад" in {btn.text for row in keyboard for btn in row}


# ===================================================================
# Cancel navigation tests
# ===================================================================


@pytest.mark.asyncio
async def test_cancel_from_interact_goes_to_main_menu(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that «Отмена» from interact_list goes to main menu."""
    user = await _create_user(async_session)
    await _create_habit(async_session, user, "Бег", 7, 8)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        msg = await full_client.send_callback("nav:cancel")

        assert "Главное меню" in msg.text


@pytest.mark.asyncio
async def test_cancel_from_manage_goes_to_main_menu(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that «Отмена» from manage_single goes to main menu."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Бег", 7, 8)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        msg = await full_client.send_callback("nav:cancel")

        assert "Главное меню" in msg.text


# ===================================================================
# editing — adapted for new two-level navigation
# ===================================================================


@pytest.mark.asyncio
async def test_edit_habit_title(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that editing a habit title updates it in the database."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Старое название")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        await full_client.send_callback(f"habit:edit:{habit.id}")
        await full_client.send_callback("edit_field:title")
        await full_client.send_message("Новое название")

    # Verify in DB
    await async_session.refresh(habit)
    assert habit.title == "Новое название"


@pytest.mark.asyncio
async def test_edit_habit_start_time(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that editing a habit start time updates it in the database."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Зарядка", 8, 9)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        await full_client.send_callback(f"habit:edit:{habit.id}")
        await full_client.send_callback("edit_field:start_time")
        await full_client.send_callback("time:06:00")

    await async_session.refresh(habit)
    assert habit.start_time == time(6, 0)


@pytest.mark.asyncio
async def test_edit_habit_start_time_invalid(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that new start_time ≥ end_time is rejected."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Работа", 9, 17)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        await full_client.send_callback(f"habit:edit:{habit.id}")
        await full_client.send_callback("edit_field:start_time")
        # Try to set start_time = 18:00 (≥ end_time 17:00)
        msg = await full_client.send_callback("time:18:00")
        assert "должно быть раньше" in msg.text

    await async_session.refresh(habit)
    assert habit.start_time == time(9, 0)


@pytest.mark.asyncio
async def test_edit_habit_end_time(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that editing a habit end time updates it in the database."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Прогулка", 18, 19)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        await full_client.send_callback(f"habit:edit:{habit.id}")
        await full_client.send_callback("edit_field:end_time")
        await full_client.send_callback("time:20:00")

    await async_session.refresh(habit)
    assert habit.end_time == time(20, 0)


@pytest.mark.asyncio
async def test_edit_habit_end_time_to_null(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that editing end_time to ``time:null`` sets it to None."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Хобби", 19, 21)

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        await full_client.send_callback(f"habit:edit:{habit.id}")
        await full_client.send_callback("edit_field:end_time")
        msg = await full_client.send_callback("time:null")
        assert "без ограничения" in msg.text

    await async_session.refresh(habit)
    assert habit.end_time is None


@pytest.mark.asyncio
async def test_edit_habit_frequency(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that editing a habit frequency updates it in the database."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Спорт", 7, 8, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        await full_client.send_callback(f"habit:edit:{habit.id}")
        await full_client.send_callback("edit_field:frequency")
        await full_client.send_callback("freq:weekends")

    await async_session.refresh(habit)
    assert habit.frequency == "weekends"


@pytest.mark.asyncio
async def test_cancel_edit(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that cancelling the edit flow returns to the habit list."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Не трогать")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        await full_client.send_callback(f"habit:edit:{habit.id}")
        # Cancel from choose_field
        msg = await full_client.send_callback("nav:cancel")
        # Returns to habit list (view_list)
        assert "Не трогать" in msg.text

    # Verify habit was NOT changed
    await async_session.refresh(habit)
    assert habit.title == "Не трогать"


# ===================================================================
# unauthorized access
# ===================================================================


@pytest.mark.asyncio
async def test_edit_habit_unauthorized(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that editing another user's habit is rejected.

    The unauthorised user is shown the "not found"-style habit list
    because the habit is scoped to the filtered user.
    """
    user_a = await _create_user(async_session, telegram_id=111111)
    await _create_user(async_session, telegram_id=222222)
    await _create_habit(async_session, user_a, "Чужое")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # user_b (222222) tries to view habits
        msg = await full_client.send_callback("main_menu:habits", user_id=222222)
        assert "У вас пока нет привычек" in msg.text


# ===================================================================
# deletion — adapted for new two-level navigation
# ===================================================================


@pytest.mark.asyncio
async def test_delete_habit_with_confirmation(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that deleting a habit after confirmation removes it from DB."""
    user = await _create_user(async_session)
    habit = await _create_habit(async_session, user, "Удалить")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit.id}")
        # Click delete from manage menu
        msg = await full_client.send_callback(f"habit:delete:{habit.id}")
        assert "Вы уверены" in msg.text

        # Confirm deletion (last reply is habit list, should be empty)
        msg = await full_client.send_callback(f"habit:confirm_delete:{habit.id}")
        assert "У вас пока нет привычек" in msg.text

    # Verify habit is gone
    stmt = select(Habit).where(Habit.id == habit.id)
    result = await async_session.execute(stmt)
    assert result.scalar_one_or_none() is None


# ===================================================================
# Conflict detection — creation
# ===================================================================


@pytest.mark.asyncio
async def test_create_habit_no_conflict(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Create a habit that does not conflict — it should be saved normally."""
    user = await _create_user(async_session)
    # Existing habit: 08:00-09:00 daily
    await _create_habit(async_session, user, "Бег", 8, 9, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Чтение")
        await full_client.send_callback("time:10:00")
        await full_client.send_callback("time:11:00")
        msg = await full_client.send_callback("freq:daily")
        assert "Привычка успешно создана" in msg.text
        assert "Чтение" in msg.text

    stmt = select(Habit).where(Habit.title == "Чтение")
    result = await async_session.execute(stmt)
    habit = result.scalar_one()
    assert habit.start_time == time(10, 0)
    assert habit.end_time == time(11, 0)
    assert habit.frequency == "daily"


@pytest.mark.asyncio
async def test_create_habit_with_conflict(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Create a habit that overlaps time+days with an existing one — conflict."""
    user = await _create_user(async_session)
    await _create_habit(async_session, user, "Бег", 8, 9, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Чтение")
        await full_client.send_callback("time:08:00")
        # End time after existing 09:00 → still overlaps
        msg = await full_client.send_callback("time:09:00")
        assert "Выберите периодичность" in msg.text

        msg = await full_client.send_callback("freq:daily")
        assert "конфликтует" in msg.text
        assert msg.reply_markup is not None

    # Habit must NOT be saved
    stmt = select(Habit).where(Habit.title == "Чтение")
    result = await async_session.execute(stmt)
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_habit_force_add(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Conflict → force_add saves the habit despite the conflict."""
    user = await _create_user(async_session)
    await _create_habit(async_session, user, "Бег", 8, 9, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Форс")
        await full_client.send_callback("time:08:00")
        await full_client.send_callback("time:09:00")
        await full_client.send_callback("freq:daily")
        # Now in ConflictHabitFSM

        msg = await full_client.send_callback("conflict_habit:force_add")
        assert "Привычка успешно создана" in msg.text
        assert "Форс" in msg.text

    stmt = select(Habit).where(Habit.title == "Форс")
    result = await async_session.execute(stmt)
    habit = result.scalar_one()
    assert habit.start_time == time(8, 0)
    assert habit.frequency == "daily"


# ===================================================================
# Conflict detection — editing
# ===================================================================


@pytest.mark.asyncio
async def test_edit_habit_frequency_creates_conflict(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Editing frequency to create a day+time overlap triggers conflict."""
    user = await _create_user(async_session)
    # A: 08:00-09:00 daily
    await _create_habit(async_session, user, "A", 8, 9, "daily")
    # B: 08:00-09:00 weekends (no conflict — different days)
    habit_b = await _create_habit(async_session, user, "B", 8, 9, "weekends")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit_b.id}")
        await full_client.send_callback(f"habit:edit:{habit_b.id}")
        await full_client.send_callback("edit_field:frequency")
        # Pick daily → now overlaps with A
        msg = await full_client.send_callback("freq:daily")
        assert "конфликтует" in msg.text

    # B should NOT have been updated
    await async_session.refresh(habit_b)
    assert habit_b.frequency == "weekends"


@pytest.mark.asyncio
async def test_edit_habit_time_creates_conflict(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Editing a habit's time to overlap with an existing one triggers conflict."""
    user = await _create_user(async_session)
    # A: 08:00-09:00 daily
    await _create_habit(async_session, user, "A", 8, 9, "daily")
    # B: 10:00-11:00 daily (no conflict)
    habit_b = await _create_habit(async_session, user, "B", 10, 11, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit_b.id}")
        await full_client.send_callback(f"habit:edit:{habit_b.id}")
        await full_client.send_callback("edit_field:start_time")
        # Pick 08:00 → now overlaps with A
        msg = await full_client.send_callback("time:08:00")
        assert "конфликтует" in msg.text

    # B should NOT have been updated
    await async_session.refresh(habit_b)
    assert habit_b.start_time == time(10, 0)


@pytest.mark.asyncio
async def test_edit_habit_change_time_resolves(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Trigger a conflict, then resolve it by picking a non-conflicting time."""
    user = await _create_user(async_session)
    # A: 08:00-09:00 daily
    await _create_habit(async_session, user, "A", 8, 9, "daily")
    # B: 10:00-11:00 daily
    habit_b = await _create_habit(async_session, user, "B", 10, 11, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit_b.id}")
        await full_client.send_callback(f"habit:edit:{habit_b.id}")
        await full_client.send_callback("edit_field:start_time")
        # Pick 08:00 → conflict!
        await full_client.send_callback("time:08:00")

        # Change time via conflict resolution
        msg = await full_client.send_callback("conflict_habit:change_time")
        assert "Выберите новое время начала" in msg.text

        # Pick 09:00 — non-conflicting (after A ends at 09:00, before B's end at 11:00)
        await full_client.send_callback("time:09:00")

    # B should have been updated
    await async_session.refresh(habit_b)
    assert habit_b.start_time == time(9, 0)


# ===================================================================
# Conflict keyboard layout
# ===================================================================


@pytest.mark.asyncio
async def test_conflict_keyboard_creation_buttons(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Conflict keyboard during creation has the right 5 buttons."""
    user = await _create_user(async_session)
    await _create_habit(async_session, user, "Бег", 8, 9, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Y")
        await full_client.send_callback("time:08:00")
        await full_client.send_callback("time:09:00")
        msg = await full_client.send_callback("freq:daily")

    keyboard = msg.reply_markup.inline_keyboard
    all_cb = {btn.callback_data for row in keyboard for btn in row}

    assert "conflict_habit:change_time" in all_cb
    assert "conflict_habit:change_frequency" in all_cb
    assert "conflict_habit:force_add" in all_cb
    assert "nav:cancel" in all_cb
    # Creation keyboard must NOT include edit_tasks
    assert "conflict_habit:edit_tasks" not in all_cb


@pytest.mark.asyncio
async def test_conflict_keyboard_edit_buttons(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Conflict keyboard during editing has all 6 buttons including edit_tasks."""
    user = await _create_user(async_session)
    await _create_habit(async_session, user, "A", 8, 9, "daily")
    habit_b = await _create_habit(async_session, user, "B", 10, 11, "daily")

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        await full_client.send_callback("main_menu:habits")
        await full_client.send_callback("habits:interact")
        await full_client.send_callback(f"habit:select:{habit_b.id}")
        await full_client.send_callback(f"habit:edit:{habit_b.id}")
        await full_client.send_callback("edit_field:start_time")
        msg = await full_client.send_callback("time:08:00")

    keyboard = msg.reply_markup.inline_keyboard
    all_cb = {btn.callback_data for row in keyboard for btn in row}

    assert "conflict_habit:change_time" in all_cb
    assert "conflict_habit:change_frequency" in all_cb
    assert "conflict_habit:edit_schedule" in all_cb
    assert "conflict_habit:edit_tasks" in all_cb
    assert "conflict_habit:force_add" in all_cb
    assert "nav:cancel" in all_cb
