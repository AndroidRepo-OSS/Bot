from asyncio import TaskGroup
from time import perf_counter
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit

import structlog
from pydantic import Field

from androidrepo_bot.repositories.http import ApiClient, ProviderModel, WebUrl, fetch_languages, raise_task_group_error
from androidrepo_bot.repositories.links import build_repository_links
from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef, RepositoryRelease

if TYPE_CHECKING:
    import aiohttp

logger = structlog.get_logger(__name__)


class GitLabLicense(ProviderModel):
    key: str | None = None
    name: str | None = None
    nickname: str | None = None


class GitLabProject(ProviderModel):
    id: int
    name: str = Field(min_length=1)
    description: str | None = None
    web_url: WebUrl
    readme_url: WebUrl | None = None
    topics: tuple[str, ...] = Field(default_factory=tuple)
    license: GitLabLicense | None = None


class GitLabReleaseLinks(ProviderModel):
    self_url: WebUrl | None = Field(default=None, validation_alias="self")


class GitLabRelease(ProviderModel):
    name: str | None = None
    tag_name: str = Field(min_length=1)
    description: str | None = None
    links: GitLabReleaseLinks = Field(default_factory=GitLabReleaseLinks, validation_alias="_links")


class GitLabClient:
    def __init__(self, *, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._api = ApiClient(client=session, provider_name="GitLab")
        self._headers = {"PRIVATE-TOKEN": token} if token else {}

    async def fetch(self, repository: RepositoryRef) -> RepositoryDetails:
        started_at = perf_counter()
        log_context = {"provider": repository.provider.value, "repository": repository.full_name}
        logger.debug("GitLab project metadata fetch started", **log_context)
        project_id = quote(repository.full_name, safe="")
        root = f"https://gitlab.com/api/v4/projects/{project_id}"
        response = await self._api.get(root, headers=self._headers, params={"license": "true"})
        metadata = await self._api.parse_model(GitLabProject, response)
        logger.debug(
            "GitLab project metadata fetched",
            **log_context,
            provider_repository_id=str(metadata.id),
            has_readme_url=metadata.readme_url is not None,
            topic_count=len(metadata.topics),
        )

        try:
            async with TaskGroup() as tasks:
                readme_task = tasks.create_task(self._fetch_readme(root, metadata.readme_url))
                languages_task = tasks.create_task(fetch_languages(self._api, root, self._headers))
                release_task = tasks.create_task(self._fetch_release(root, repository))
        except ExceptionGroup as error:
            raise_task_group_error(error)

        readme = readme_task.result()
        languages = languages_task.result()
        release = release_task.result()

        links = await build_repository_links(
            metadata.web_url,
            release_url=release.url if release else None,
            homepage=None,
            readme=readme,
            readme_url=metadata.readme_url,
        )
        details = RepositoryDetails(
            ref=repository,
            provider_repository_id=str(metadata.id),
            display_name=metadata.name,
            description=metadata.description,
            readme=readme,
            languages=languages,
            license=_license_name(metadata.license),
            topics=metadata.topics,
            homepage=None,
            release=release,
            links=links,
        )
        logger.debug(
            "GitLab repository evidence normalized",
            **log_context,
            duration_seconds=perf_counter() - started_at,
            has_readme=readme is not None,
            has_release=release is not None,
            language_count=len(languages),
            link_count=len(links),
        )
        return details

    async def _fetch_readme(self, root: str, readme_url: str | None) -> str | None:
        file_path = _readme_path(readme_url)
        if file_path is None:
            logger.debug("GitLab README path unavailable")
            return None

        response = await self._api.get_optional(
            f"{root}/repository/files/{quote(file_path, safe='')}/raw", headers=self._headers, params={"ref": "HEAD"}
        )
        if response is None:
            logger.debug("GitLab README raw file not found")
            return None

        readme = response.text
        logger.debug("GitLab README fetched", readme_bytes=len(readme.encode()))
        return readme

    async def _fetch_release(self, root: str, repository: RepositoryRef) -> RepositoryRelease | None:
        response = await self._api.get_optional(f"{root}/releases/permalink/latest", headers=self._headers)
        if response is None:
            logger.debug("GitLab latest release not found")
            return None

        release = await self._api.parse_model(GitLabRelease, response)
        release_url = release.links.self_url or f"{repository.url}/-/releases/{quote(release.tag_name, safe='')}"
        logger.debug("GitLab latest release fetched", release_tag=release.tag_name)
        return RepositoryRelease(
            name=release.name or release.tag_name,
            tag=release.tag_name,
            url=release_url,
            description=release.description,
        )


def _readme_path(readme_url: str | None) -> str | None:
    if not readme_url:
        return None

    marker = "/-/blob/"
    path = urlsplit(readme_url).path
    _, found, remainder = path.partition(marker)
    if not found:
        return None

    _, separator, file_path = remainder.partition("/")
    return unquote(file_path) if separator and file_path else None


def _license_name(license_data: GitLabLicense | None) -> str | None:
    if license_data is None:
        return None

    return license_data.nickname or license_data.key or license_data.name
