# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

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
from .services import PreviewDebugRegistry, TelegramLogger

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from sqlalchemy.ext.asyncio import AsyncEngine

    from .config import BotSettings
    from .db import AsyncSessionMaker


def setup_dependencies(dp: Dispatcher, bot: Bot, settings: BotSettings) -> None:
    dp["settings"] = settings
    dp["preview_registry"] = PreviewDebugRegistry()

    gh_token = settings.resolved_github_token
    dp["summary_agent"] = SummaryAgent(api_key=gh_token)
    dp["revision_agent"] = RevisionAgent(api_key=gh_token)

    session: ClientSession | None = None
    db_engine: AsyncEngine | None = None
    db_session_maker: AsyncSessionMaker | None = None

    @dp.startup()
    async def on_startup() -> None:
        nonlocal session, db_engine, db_session_maker
        session = ClientSession(timeout=ClientTimeout(total=30))

        github_fetcher = GitHubRepositoryFetcher(session=session, token=gh_token)
        gitlab_fetcher = GitLabRepositoryFetcher(session=session, token=settings.resolved_gitlab_token)
        dp["github_fetcher"] = github_fetcher
        dp["gitlab_fetcher"] = gitlab_fetcher

        db_engine = create_engine(settings.database_url)
        db_session_maker = create_session_maker(db_engine)
        await init_models(db_engine)
        if settings.database_url.startswith("sqlite"):
            await apply_sqlite_pragmas(db_engine)
            await vacuum_and_analyze(db_engine)

        dp["db_engine"] = db_engine
        dp["db_session_maker"] = db_session_maker
        dp["posts_repository"] = PostsRepository(db_session_maker)

        telegram_logger = TelegramLogger(bot=bot, chat_id=settings.allowed_chat_id, topic_id=settings.logs_topic_id)
        dp["telegram_logger"] = telegram_logger

        await telegram_logger.log_bot_started()

    @dp.shutdown()
    async def on_shutdown() -> None:
        nonlocal session, db_engine, db_session_maker
        if session is not None:
            await session.close()
            session = None

        if db_engine is not None:
            await db_engine.dispose()
            db_engine = None
        db_session_maker = None
