"""Telegram admission, update lifetime, and error reporting."""

from asyncio import Event
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, Protocol, override

import structlog
from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.dispatcher.middlewares.user_context import EventContext
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import ErrorEvent, Message, TelegramObject, Update
from aiogram.utils.formatting import Bold, as_list
from structlog.contextvars import bind_contextvars, clear_contextvars

logger = structlog.get_logger(__name__)
type Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[object]]


class Polling(Protocol):
    """The polling API we use, without aiogram's dynamically typed UNSET default."""

    def resolve_used_update_types(self) -> list[str]: ...

    async def start_polling(self, *bots: Bot, allowed_updates: list[str], close_bot_session: bool) -> None: ...


class DrainingDispatcher(Dispatcher):
    """Finish admitted updates before aiogram closes FSM storage and other resources."""

    def __init__(self, **workflow_data: object) -> None:
        super().__init__(
            storage=MemoryStorage(),
            events_isolation=SimpleEventIsolation(),
            fsm_strategy=FSMStrategy.USER_IN_CHAT,
            disable_fsm=False,
            name="androidrepo_bot",
            **workflow_data,
        )
        self._active_updates = 0
        self._closing = False
        self._idle = Event()
        self._idle.set()

    @override
    async def feed_update(self, bot: Bot, update: Update, **kwargs: Any) -> Any:
        if self._closing:
            return None
        self._active_updates += 1
        self._idle.clear()
        try:
            return await super().feed_update(bot, update, **kwargs)
        finally:
            self._active_updates -= 1
            if not self._active_updates:
                self._idle.set()

    @override
    async def emit_shutdown(self, *args: Any, **kwargs: Any) -> None:
        # Includes updates waiting for the FSM lock, not just running handlers.
        self._closing = True
        await self._idle.wait()
        await super().emit_shutdown(*args, **kwargs)


class StaffTopicMiddleware(BaseMiddleware):
    def __init__(self, *, staff_chat_id: int, post_topic_id: int) -> None:
        self._staff_chat_id = staff_chat_id
        self._post_topic_id = post_topic_id
        self._start = CommandStart()

    @override
    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> object | None:
        if not isinstance(event, Update):
            return None
        clear_contextvars()
        context = data.get("event_context")
        if not isinstance(context, EventContext):
            return None
        bind_contextvars(
            update_id=event.update_id,
            chat_id=context.chat_id,
            message_thread_id=context.thread_id,
            user_id=context.user_id,
        )
        bot = data.get("bot")
        is_start = event.message is not None and isinstance(bot, Bot) and await self._start(event.message, bot)
        is_staff = (
            context.chat_id == self._staff_chat_id
            and context.thread_id == self._post_topic_id
            and context.user_id is not None
        )
        if not is_start and not is_staff:
            logger.debug("Telegram update ignored")
            return None
        started_at = perf_counter()
        try:
            return await handler(event, data)
        finally:
            logger.debug("Telegram update finished", duration_seconds=perf_counter() - started_at)


async def handle_error(event: ErrorEvent) -> bool:
    # Telegram exceptions can embed message text or request parameters.
    logger.error("Telegram update failed", error_type=type(event.exception).__name__)
    message = event.update.message
    if event.update.callback_query is not None and isinstance(event.update.callback_query.message, Message):
        message = event.update.callback_query.message
    if message is None:
        return True
    try:
        await message.answer(**as_list(Bold("Request failed"), "Try again in a moment.").as_kwargs())
    except TelegramAPIError as error:
        logger.warning("Failed to send the error response", error_type=type(error).__name__)
    return True
