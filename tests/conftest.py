"""Pytest fixtures for async database and bot handler tests."""

import asyncio
import importlib
from dataclasses import dataclass
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    Update,
    User as TgUser,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.db.models import Base


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def async_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a temporary async session backed by an in-memory SQLite database.

    The database schema is created before each test and dropped after.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# Fake Telegram API session — intercepts all outgoing requests
# ---------------------------------------------------------------------------


class MockTelegramSession(BaseSession):
    """A fake Telegram API session that captures outgoing messages.

    Instead of making real HTTP requests, it records every ``Message``
    that the bot tries to send and returns a dummy response.
    """

    def __init__(self) -> None:
        super().__init__()
        self.captured: list[Message] = []

    async def __call__(self, bot: Bot, method, timeout=None):
        """Intercept any API method call (send_message, answer_callback_query, …).

        Args:
            bot: The Bot instance making the request.
            method: The API method object (e.g. SendMessage).
            timeout: Request timeout (ignored).

        Returns:
            A dummy ``Message`` that is also appended to ``captured``.
        """
        text = getattr(method, "text", "")
        reply_markup = getattr(method, "reply_markup", None)
        chat_id = getattr(method, "chat_id", 0)
        msg = Message(
            message_id=2,
            date=0,
            chat=Chat(id=chat_id, type="private"),
            text=text,
            reply_markup=reply_markup,
        )
        self.captured.append(msg)
        return msg

    async def close(self):
        """No-op close."""

    async def make_request(self, bot: Bot, method, timeout=None):
        """Delegate to __call__ for compatibility with BaseSession."""
        return await self(bot, method, timeout=timeout)

    async def stream_content(self, *args, **kwargs):
        """No-op stream_content (not used in tests)."""
        raise NotImplementedError("stream_content is not used in tests")


# ---------------------------------------------------------------------------
# Bot / Dispatcher fixtures for handler tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def test_bot() -> Bot:
    """Return a Bot instance backed by MockTelegramSession — no real HTTP."""
    session = MockTelegramSession()
    bot = Bot(token="123456:ABC-DEF1234ghik", session=session)
    return bot


@pytest_asyncio.fixture(scope="function")
async def test_dispatcher() -> Dispatcher:
    """Return a fresh Dispatcher with a fresh copy of the common router.

    The ``src.handlers.common`` module is reloaded before each test so that
    its singleton router can be attached to a new Dispatcher without raising
    "Router is already attached".
    """
    import src.handlers.common  # noqa: F811

    importlib.reload(src.handlers.common)
    from src.handlers.common import router as common_router  # noqa: F811

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(common_router)
    return dp


# ---------------------------------------------------------------------------
# TestClient — lightweight helper to emulate Telegram updates
# ---------------------------------------------------------------------------


@dataclass
class TestClient:
    """Minimal test client that feeds updates into a Dispatcher.

    Attributes:
        bot: The Bot instance (its session is a MockTelegramSession).
        dp: The Dispatcher instance under test.
    """

    bot: Bot
    dp: Dispatcher

    async def send_message(self, text: str, user_id: int = 123456) -> Message:
        """Emulate a user sending a text message.

        Args:
            text: The message text (e.g. ``/start``).
            user_id: Telegram user ID of the sender.

        Returns:
            The Message object produced by the first handler answer.
        """
        update = Update(
            update_id=1,
            message=Message(
                message_id=1,
                date=0,
                chat=Chat(id=user_id, type="private"),
                from_user=TgUser(id=user_id, is_bot=False, first_name="Test"),
                text=text,
            ),
        )
        return await self._feed_and_get_answer(update, user_id)

    async def send_callback(
        self,
        callback_data: str,
        user_id: int = 123456,
        message_text: str = "menu",
    ) -> Message:
        """Emulate a user tapping an inline button.

        Args:
            callback_data: The callback_data string from the button.
            user_id: Telegram user ID.
            message_text: Text of the message the button is attached to.

        Returns:
            The Message object produced by the handler's answer.
        """
        update = Update(
            update_id=2,
            callback_query=CallbackQuery(
                id="cb_1",
                from_user=TgUser(id=user_id, is_bot=False, first_name="Test"),
                chat_instance=str(user_id),
                data=callback_data,
                message=Message(
                    message_id=1,
                    date=0,
                    chat=Chat(id=user_id, type="private"),
                    text=message_text,
                ),
            ),
        )
        return await self._feed_and_get_answer(update, user_id)

    async def _feed_and_get_answer(self, update: Update, user_id: int) -> Message:
        """Feed an update to the dispatcher and capture the bot's answer.

        Clears the session's captured list before feeding, then returns
        the last captured ``Message``.

        Args:
            update: The Update object to feed.
            user_id: Telegram user ID (used for FSM key).

        Returns:
            The Message that the handler attempted to send.
        """
        session: MockTelegramSession = self.bot.session  # type: ignore[assignment]
        session.captured.clear()
        await self.dp.feed_update(self.bot, update)
        if not session.captured:
            raise RuntimeError("No message was sent by the handler")
        return session.captured[-1]


@pytest_asyncio.fixture(scope="function")
async def client(test_bot: Bot, test_dispatcher: Dispatcher) -> TestClient:
    """Provide a TestClient wired to the test bot and dispatcher."""
    return TestClient(bot=test_bot, dp=test_dispatcher)
