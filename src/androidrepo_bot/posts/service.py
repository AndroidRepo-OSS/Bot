from asyncio import Lock
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

from androidrepo_bot.db.publications import publication_cooldown, record_blocked_attempt, record_publication
from androidrepo_bot.db.repositories import register_repository
from androidrepo_bot.media.models import BannerImage, BannerRequest
from androidrepo_bot.posts.models import (
    CooldownBlockedError,
    PostCreation,
    PostDraft,
    PublicationCooldown,
    PublicationRecord,
    RegisteredRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from androidrepo_bot.generation.service import GenerationService
    from androidrepo_bot.media.banner import BannerService
    from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef
    from androidrepo_bot.repositories.service import RepositoryService

type ProgressCallback = Callable[[], Awaitable[None]]

logger = structlog.get_logger(__name__)


class PostService:
    def __init__(
        self,
        *,
        repositories: RepositoryService,
        generation: GenerationService,
        banners: BannerService,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self.repositories = repositories
        self.generation = generation
        self.banners = banners
        self.sessions = sessions
        self._publication_locks: dict[int, Lock] = {}

    async def create(
        self, repository: RepositoryRef, *, requested_by_user_id: int, progress: ProgressCallback | None = None
    ) -> PostCreation:
        details = await self.repositories.get(repository)
        if progress is not None:
            await progress()

        registered = await register_repository(self.sessions, details, repository)
        cooldown = await publication_cooldown(self.sessions, registered.id)
        if not cooldown.allowed:
            await record_blocked_attempt(self.sessions, registered, cooldown, requested_by_user_id=requested_by_user_id)
            raise CooldownBlockedError(cooldown)

        draft = await self.generation.generate(details)
        if progress is not None:
            await progress()
        return PostCreation(details, registered, draft)

    async def regenerate(self, repository: RepositoryDetails) -> PostDraft:
        return await self.generation.generate(repository)

    async def render_banner(self, draft: PostDraft, repository: RepositoryDetails) -> BannerImage:
        return await self.banners.render(
            BannerRequest(
                project_name=draft.title,
                repository=repository.ref.full_name,
                provider=repository.ref.provider.display_name,
                primary_language=(repository.languages[0] if repository.languages else None),
                license_name=repository.license,
                release=(repository.release.tag if repository.release is not None else None),
                topics=repository.topics[:3],
            )
        )

    def publication_lock(self, repository_id: int) -> Lock:
        return self._publication_locks.setdefault(repository_id, Lock())

    async def check_publication_cooldown(
        self, repository: RegisteredRepository, *, requested_by_user_id: int
    ) -> PublicationCooldown:
        cooldown = await publication_cooldown(self.sessions, repository.id)
        if not cooldown.allowed:
            await record_blocked_attempt(self.sessions, repository, cooldown, requested_by_user_id=requested_by_user_id)
        return cooldown

    async def record_publication(self, publication: PublicationRecord) -> bool:
        inserted = await record_publication(self.sessions, publication)
        logger.info(
            "Publication recorded" if inserted else "Publication was already recorded",
            repository_id=publication.repository.id,
            channel_id=publication.channel_id,
            channel_message_id=publication.channel_message_id,
            inserted=inserted,
        )
        return inserted
