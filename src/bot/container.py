# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Unpack

from aiogram import Dispatcher
from aiogram.dispatcher.middlewares.data import MiddlewareData
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiohttp import ClientSession, ClientTimeout

from .db import (
    PostsRepository,
    apply_sqlite_pragmas,
    create_engine,
    create_session_maker,
    init_models,
    vacuum_and_analyze,
)
from .integrations.ai import RevisionAgent, SummaryAgent
from .integrations.repositories import GitHubRepositoryFetcher, GitLabRepositoryFetcher
from .modules import register_modules
from .services import PreviewDebugRegistry, TelegramLogger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncEngine

    from .config import BotSettings
    from .db import AsyncSessionMaker


class AppWorkflowData(MiddlewareData, total=False):
    settings: BotSettings
    preview_registry: PreviewDebugRegistry
    summary_agent: SummaryAgent
    revision_agent: RevisionAgent
    github_fetcher: GitHubRepositoryFetcher
    gitlab_fetcher: GitLabRepositoryFetcher
    db_engine: AsyncEngine
    db_session_maker: AsyncSessionMaker
    posts_repository: PostsRepository
    telegram_logger: TelegramLogger


def create_dispatcher(*, bot: Bot, settings: BotSettings) -> Dispatcher:
    github_token = settings.resolved_github_token
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        events_isolation=SimpleEventIsolation(),
        settings=settings,
        preview_registry=PreviewDebugRegistry(),
        summary_agent=SummaryAgent(api_key=github_token),
        revision_agent=RevisionAgent(api_key=github_token),
    )

    register_modules(dispatcher, allowed_chat_id=settings.allowed_chat_id, post_topic_id=settings.post_topic_id)

    runtime = ApplicationRuntime(dispatcher=dispatcher, bot=bot, settings=settings, github_token=github_token)
    dispatcher.startup.register(runtime.startup)
    dispatcher.shutdown.register(runtime.shutdown)
    return dispatcher


def _update_workflow_data(dispatcher: Dispatcher, **kwargs: Unpack[AppWorkflowData]) -> None:
    dispatcher.workflow_data.update(kwargs)


@dataclass(slots=True)
class ApplicationRuntime:
    dispatcher: Dispatcher
    bot: Bot
    settings: BotSettings
    github_token: str
    session: ClientSession | None = field(default=None, init=False)
    db_engine: AsyncEngine | None = field(default=None, init=False)
    db_session_maker: AsyncSessionMaker | None = field(default=None, init=False)

    async def startup(self) -> None:
        self.session = ClientSession(timeout=ClientTimeout(total=30))

        github_fetcher = GitHubRepositoryFetcher(session=self.session, token=self.github_token)
        gitlab_fetcher = GitLabRepositoryFetcher(session=self.session, token=self.settings.resolved_gitlab_token)

        self.db_engine = create_engine(self.settings.database_url)
        self.db_session_maker = create_session_maker(self.db_engine)
        await init_models(self.db_engine)
        if self.settings.database_url.startswith("sqlite"):
            await apply_sqlite_pragmas(self.db_engine)
            await vacuum_and_analyze(self.db_engine)

        posts_repository = PostsRepository(self.db_session_maker)
        telegram_logger = TelegramLogger(
            bot=self.bot, chat_id=self.settings.allowed_chat_id, topic_id=self.settings.logs_topic_id
        )

        _update_workflow_data(
            self.dispatcher,
            github_fetcher=github_fetcher,
            gitlab_fetcher=gitlab_fetcher,
            db_engine=self.db_engine,
            db_session_maker=self.db_session_maker,
            posts_repository=posts_repository,
            telegram_logger=telegram_logger,
        )

        await telegram_logger.log_bot_started()

    async def shutdown(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

        if self.db_engine is not None:
            await self.db_engine.dispose()
            self.db_engine = None

        self.db_session_maker = None

        for key in (
            "github_fetcher",
            "gitlab_fetcher",
            "db_engine",
            "db_session_maker",
            "posts_repository",
            "telegram_logger",
        ):
            self.dispatcher.workflow_data.pop(key, None)
