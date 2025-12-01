# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from aiohttp import ClientSession, ClientTimeout

from .integrations.ai import RevisionAgent, SummaryAgent
from .integrations.repositories import GitHubRepositoryFetcher, GitLabRepositoryFetcher
from .services import BannerGenerator, PreviewDebugRegistry

if TYPE_CHECKING:
    from aiogram import Dispatcher


class ContainerSettings(Protocol):
    @property
    def resolved_ghmodels_api_key(self) -> str: ...

    @property
    def resolved_github_token(self) -> str | None: ...

    @property
    def resolved_gitlab_token(self) -> str | None: ...

    @property
    def post_channel_id(self) -> int: ...

    @property
    def post_topic_id(self) -> int: ...


@dataclass(slots=True)
class BotDependencies:
    settings: ContainerSettings
    session: ClientSession
    github_fetcher: GitHubRepositoryFetcher
    gitlab_fetcher: GitLabRepositoryFetcher
    summary_agent: SummaryAgent
    revision_agent: RevisionAgent
    banner_generator: BannerGenerator
    preview_registry: PreviewDebugRegistry


def setup_dependencies(dp: Dispatcher, settings: ContainerSettings) -> None:
    session: ClientSession | None = None

    @dp.startup()
    async def on_startup() -> None:  # noqa: RUF029
        nonlocal session
        timeout = ClientTimeout(total=30)
        session = ClientSession(timeout=timeout)

        github_fetcher = GitHubRepositoryFetcher(session=session, token=settings.resolved_github_token)
        gitlab_fetcher = GitLabRepositoryFetcher(session=session, token=settings.resolved_gitlab_token)

        ai_api_key = settings.resolved_ghmodels_api_key
        summary_agent = SummaryAgent(api_key=ai_api_key)
        revision_agent = RevisionAgent(api_key=ai_api_key)

        banner_generator = BannerGenerator()
        preview_registry = PreviewDebugRegistry()

        dp["bot_dependencies"] = BotDependencies(
            settings=settings,
            session=session,
            github_fetcher=github_fetcher,
            gitlab_fetcher=gitlab_fetcher,
            summary_agent=summary_agent,
            revision_agent=revision_agent,
            banner_generator=banner_generator,
            preview_registry=preview_registry,
        )

    @dp.shutdown()
    async def on_shutdown() -> None:
        nonlocal session
        if session is not None:
            await session.close()
            session = None
