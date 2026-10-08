from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

import structlog
import uvloop
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from androidrepo_bot.admin import AdminLog
from androidrepo_bot.config import Settings
from androidrepo_bot.db.engine import database_sessions
from androidrepo_bot.dispatcher import DrainingDispatcher, StaffTopicMiddleware, handle_error
from androidrepo_bot.generation.service import create_post_agent, create_zen_model
from androidrepo_bot.http import create_http_session
from androidrepo_bot.log_config import configure_logging
from androidrepo_bot.posts.callbacks import router as post_callbacks
from androidrepo_bot.posts.commands import router as post_commands
from androidrepo_bot.posts.drafts import DraftWorkflow
from androidrepo_bot.posts.publication import PublicationWorkflow
from androidrepo_bot.repositories.github import GitHubClient
from androidrepo_bot.repositories.gitlab import GitLabClient
from androidrepo_bot.repositories.models import RepositoryProvider

if TYPE_CHECKING:
    from pydantic import SecretStr

    from androidrepo_bot.dispatcher import Polling

logger = structlog.get_logger(__name__)

START_COMMAND = BotCommand(command="start", description="About the bot and community")
STAFF_COMMANDS = [
    START_COMMAND,
    BotCommand(command="post", description="Create a repository post"),
    BotCommand(command="cancel", description="Discard the active draft"),
    BotCommand(command="reconcile", description="Resolve a pending publication"),
]


def build_dispatcher(
    settings: Settings, drafts: DraftWorkflow, publications: PublicationWorkflow, admin_log: AdminLog
) -> Polling:
    dispatcher = DrainingDispatcher(drafts=drafts, publications=publications, admin_log=admin_log)
    # Admission happens before waiting for or reading a user's FSM state.
    dispatcher.update.outer_middleware.unregister(dispatcher.fsm)
    dispatcher.update.outer_middleware(
        StaffTopicMiddleware(staff_chat_id=settings.staff_chat_id, post_topic_id=settings.post_topic_id)
    )
    dispatcher.update.outer_middleware(dispatcher.fsm)
    dispatcher.include_routers(post_commands, post_callbacks)
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

        admin_log = AdminLog(bot=bot, chat_id=settings.staff_chat_id, topic_id=settings.log_topic_id)
        drafts = DraftWorkflow(
            bot=bot,
            providers={
                RepositoryProvider.GITHUB: GitHubClient(session=http, token=_secret_value(settings.github_token)),
                RepositoryProvider.GITLAB: GitLabClient(session=http, token=_secret_value(settings.gitlab_token)),
            },
            agent=agent,
            admin_log=admin_log,
            http=http,
            sessions=sessions,
        )
        publications = PublicationWorkflow(bot=bot, channel_id=settings.channel_id, sessions=sessions)
        dispatcher = build_dispatcher(settings, drafts, publications, admin_log)

        await bot.set_my_commands([START_COMMAND], scope=BotCommandScopeDefault())
        await bot.set_my_commands(STAFF_COMMANDS, scope=BotCommandScopeChat(chat_id=settings.staff_chat_id))
        await admin_log.bot_started()
        try:
            await dispatcher.start_polling(
                bot, allowed_updates=dispatcher.resolve_used_update_types(), close_bot_session=False
            )
        finally:
            await admin_log.bot_stopped()


def _secret_value(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret is not None else None


def main() -> None:
    settings = Settings.model_validate({})
    configure_logging(settings.log_level)
    try:
        uvloop.run(run_bot(settings))
    except KeyboardInterrupt:
        logger.info("Bot stopped by the operator")
