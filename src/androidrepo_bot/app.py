from asyncio import gather
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast, override

import structlog
from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import MessageEntityType
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    CallbackQuery,
    ErrorEvent,
    Message,
    TelegramObject,
    Update,
)
from aiogram.utils.formatting import Bold, as_list
from structlog.contextvars import bind_contextvars, clear_contextvars

from androidrepo_bot.admin import AdminLog
from androidrepo_bot.db.engine import database_sessions
from androidrepo_bot.generation.service import GenerationService, create_post_agent, create_zen_model
from androidrepo_bot.posts.callbacks import router as post_callbacks
from androidrepo_bot.posts.commands import router as post_commands
from androidrepo_bot.posts.drafts import DraftPreparer, DraftWorkflow
from androidrepo_bot.posts.publication import PublicationWorkflow
from androidrepo_bot.repositories.github import GitHubClient
from androidrepo_bot.repositories.gitlab import GitLabClient
from androidrepo_bot.repositories.http import create_http_session
from androidrepo_bot.repositories.models import RepositoryProvider
from androidrepo_bot.start import router as start_router

if TYPE_CHECKING:
    from pydantic import SecretStr

    from androidrepo_bot.config import Settings

logger = structlog.get_logger(__name__)
START_COMMAND = BotCommand(command="start", description="About the bot and community")
STAFF_COMMANDS = [
    START_COMMAND,
    BotCommand(command="post", description="Create a repository post"),
    BotCommand(command="cancel", description="Discard the active draft"),
    BotCommand(command="reconcile", description="Resolve a pending publication"),
]
type Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[object]]


class StaffTopicMiddleware(BaseMiddleware):
    def __init__(self, *, staff_chat_id: int, post_topic_id: int) -> None:
        self._staff_chat_id = staff_chat_id
        self._post_topic_id = post_topic_id

    @override
    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> object | None:
        clear_contextvars()
        if isinstance(event, Update):
            bind_contextvars(update_id=event.update_id)
        message = event_message(event)
        actor_id = _event_actor_id(event, message)
        if message is not None:
            bind_contextvars(
                chat_id=message.chat.id,
                message_id=message.message_id,
                message_thread_id=message.message_thread_id,
                user_id=actor_id,
            )
        if not self._is_allowed(message):
            logger.debug("Telegram update ignored")
            return None
        started_at = perf_counter()
        result = await handler(event, data)
        logger.debug("Telegram update handled", duration_seconds=perf_counter() - started_at)
        return result

    def _is_allowed(self, message: Message | None) -> bool:
        if message is None:
            return False
        if _is_start_command(message):
            return True
        return (
            message.chat.id == self._staff_chat_id
            and message.is_topic_message is True
            and message.message_thread_id == self._post_topic_id
        )


def build_dispatcher(
    settings: Settings, drafts: DraftWorkflow, publications: PublicationWorkflow, admin_log: AdminLog
) -> Dispatcher:
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        fsm_strategy=FSMStrategy.USER_IN_CHAT,
        events_isolation=SimpleEventIsolation(),
        settings=settings,
        drafts=drafts,
        publications=publications,
        admin_log=admin_log,
    )
    dispatcher.update.outer_middleware(
        StaffTopicMiddleware(staff_chat_id=settings.staff_chat_id, post_topic_id=settings.post_topic_id)
    )
    router = Router(name="androidrepo_bot")
    router.include_routers(start_router, post_commands, post_callbacks)
    dispatcher.include_router(router)
    dispatcher.errors.register(handle_error)
    return dispatcher


async def run_bot(settings: Settings) -> None:
    bot = Bot(token=settings.bot_token.get_secret_value(), default=DefaultBotProperties(link_preview_is_disabled=True))

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(bot)
        http = await stack.enter_async_context(create_http_session())
        sessions = await stack.enter_async_context(database_sessions(settings.database_url.get_secret_value()))

        model = create_zen_model(
            api_key=settings.opencode_zen_api_key.get_secret_value(), model_name=settings.opencode_zen_model
        )
        agent = create_post_agent(model)
        await stack.enter_async_context(agent)

        generation = GenerationService(agent=agent)
        admin_log = AdminLog(bot=bot, chat_id=settings.staff_chat_id, topic_id=settings.log_topic_id)
        preparer = DraftPreparer(
            providers={
                RepositoryProvider.GITHUB: GitHubClient(session=http, token=_secret_value(settings.github_token)),
                RepositoryProvider.GITLAB: GitLabClient(session=http, token=_secret_value(settings.gitlab_token)),
            },
            generation=generation,
            http=http,
            sessions=sessions,
        )
        drafts = DraftWorkflow(preparer=preparer, admin_log=admin_log)
        publications = PublicationWorkflow(bot=bot, channel_id=settings.channel_id, sessions=sessions)
        dispatcher = build_dispatcher(settings, drafts, publications, admin_log)

        await bot.set_my_commands([START_COMMAND], scope=BotCommandScopeDefault())
        await bot.set_my_commands(STAFF_COMMANDS, scope=BotCommandScopeChat(chat_id=settings.staff_chat_id))
        await admin_log.bot_started()
        try:
            start_polling = cast("Callable[..., Awaitable[None]]", getattr(dispatcher, "start_polling"))
            await start_polling(bot, close_bot_session=False)
        finally:
            await drain_update_tasks(dispatcher)
            await admin_log.bot_stopped()


async def drain_update_tasks(dispatcher: Dispatcher) -> None:
    pending = tuple(getattr(dispatcher, "_handle_update_tasks"))
    if not pending:
        return
    results = await gather(*pending, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error(
                "Update task escaped dispatcher error handling",
                error_type=type(result).__name__,
                exc_info=(type(result), result, result.__traceback__),
            )


async def handle_error(event: ErrorEvent) -> bool:
    exception = event.exception
    logger.error(
        "Unhandled exception while processing a Telegram update",
        error_type=type(exception).__name__,
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    message = event_message(event.update)
    if message is None:
        return True
    try:
        await message.answer(**as_list(Bold("Request failed"), "Try again in a moment.").as_kwargs())
    except TelegramAPIError:
        logger.exception("Failed to send the error response")
    return True


def event_message(event: TelegramObject) -> Message | None:
    if not isinstance(event, Update):
        return None
    try:
        telegram_event = event.event
    except LookupError:
        return None
    if isinstance(telegram_event, Message):
        return telegram_event
    if isinstance(telegram_event, CallbackQuery) and isinstance(telegram_event.message, Message):
        return telegram_event.message
    return None


def _event_actor_id(event: TelegramObject, message: Message | None) -> int | None:
    if isinstance(event, Update) and event.callback_query is not None:
        return event.callback_query.from_user.id
    if message is not None and message.from_user is not None:
        return message.from_user.id
    return None


def _is_start_command(message: Message) -> bool:
    if message.text is None or not message.entities:
        return False
    first_entity = message.entities[0]
    if first_entity.type != MessageEntityType.BOT_COMMAND or first_entity.offset != 0:
        return False
    command = first_entity.extract_from(message.text).partition("@")[0]
    return command.casefold() == "/start"


def _secret_value(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret is not None else None
