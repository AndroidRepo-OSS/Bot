# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import ClientSession, ClientTimeout

from .integrations.ai import RevisionAgent, SummaryAgent
from .integrations.repositories import GitHubRepositoryFetcher, GitLabRepositoryFetcher
from .services import PreviewDebugRegistry, TelegramLogger

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher

    from .config import BotSettings


def setup_dependencies(dp: Dispatcher, bot: Bot, settings: BotSettings) -> None:
    dp["settings"] = settings
    dp["preview_registry"] = PreviewDebugRegistry()

    ai_api_key = settings.resolved_ghmodels_api_key
    dp["summary_agent"] = SummaryAgent(api_key=ai_api_key)
    dp["revision_agent"] = RevisionAgent(api_key=ai_api_key)

    session: ClientSession | None = None

    @dp.startup()
    async def on_startup() -> None:
        nonlocal session
        session = ClientSession(timeout=ClientTimeout(total=30))

        github_fetcher = GitHubRepositoryFetcher(session=session, token=settings.resolved_github_token)
        gitlab_fetcher = GitLabRepositoryFetcher(session=session, token=settings.resolved_gitlab_token)
        dp["github_fetcher"] = github_fetcher
        dp["gitlab_fetcher"] = gitlab_fetcher

        telegram_logger = TelegramLogger(bot=bot, chat_id=settings.allowed_chat_id, topic_id=settings.logs_topic_id)
        dp["telegram_logger"] = telegram_logger

        await telegram_logger.log_bot_started()

    @dp.shutdown()
    async def on_shutdown() -> None:
        nonlocal session
        if session is not None:
            await session.close()
            session = None
