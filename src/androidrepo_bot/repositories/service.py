from time import perf_counter
from typing import TYPE_CHECKING

import structlog

from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryProvider, RepositoryRef

if TYPE_CHECKING:
    from androidrepo_bot.repositories.github import GitHubClient
    from androidrepo_bot.repositories.gitlab import GitLabClient

logger = structlog.get_logger(__name__)


class RepositoryService:
    def __init__(self, *, github: GitHubClient, gitlab: GitLabClient) -> None:
        self.github = github
        self.gitlab = gitlab

    async def get(self, repository: RepositoryRef) -> RepositoryDetails:
        started_at = perf_counter()
        context = {"provider": repository.provider.value, "repository": repository.full_name}
        logger.info("Repository fetch started", **context)
        try:
            match repository.provider:
                case RepositoryProvider.GITHUB:
                    details = await self.github.fetch(repository)
                case RepositoryProvider.GITLAB:
                    details = await self.gitlab.fetch(repository)
        except Exception as error:
            logger.warning(
                "Repository fetch failed",
                **context,
                duration_seconds=perf_counter() - started_at,
                error_type=type(error).__name__,
            )
            raise
        logger.info(
            "Repository fetch completed",
            **context,
            duration_seconds=perf_counter() - started_at,
            provider_repository_id=details.provider_repository_id,
            has_readme=details.readme is not None,
            has_release=details.release is not None,
            link_count=len(details.links),
        )
        return details
