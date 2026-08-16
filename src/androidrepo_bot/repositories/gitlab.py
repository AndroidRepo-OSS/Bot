from asyncio import to_thread
from time import perf_counter
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit

import structlog
from pydantic import Field

from androidrepo_bot.errors import ExternalServiceError
from androidrepo_bot.repositories.http import ProviderHttpClient, ProviderTransport
from androidrepo_bot.repositories.links import build_repository_links
from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef, RepositoryRelease
from androidrepo_bot.repositories.payloads import ProviderPayload, require_repository_path
from androidrepo_bot.repositories.resources import fetch_languages, fetch_repository_resources

if TYPE_CHECKING:
    import aiohttp

logger = structlog.get_logger(__name__)


class _GitLabLicensePayload(ProviderPayload):
    key: str | None = None
    name: str | None = None
    nickname: str | None = None


class _GitLabProjectPayload(ProviderPayload):
    id: int
    name: str = Field(min_length=1)
    path_with_namespace: str = Field(min_length=1)
    description: str | None = None
    readme_url: str | None = None
    default_branch: str | None = None
    topics: tuple[str, ...] = Field(default_factory=tuple)
    license: _GitLabLicensePayload | None = None


class _GitLabReleasePayload(ProviderPayload):
    name: str | None = None
    tag_name: str = Field(min_length=1)
    description: str | None = None


class GitLabClient:
    def __init__(self, *, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._http: ProviderTransport = ProviderHttpClient(client=session, provider_name="GitLab")
        self._headers = {"PRIVATE-TOKEN": token} if token else {}

    async def fetch(self, repository: RepositoryRef) -> RepositoryDetails:
        started_at = perf_counter()
        log_context = {"provider": repository.provider.value, "repository": repository.full_name}
        logger.debug("GitLab project metadata fetch started", **log_context)
        project_id = quote(repository.full_name, safe="")
        root = f"https://gitlab.com/api/v4/projects/{project_id}"
        response = await self._http.get(root, headers=self._headers, params={"license": "true"})
        metadata = await self._http.parse(response, _GitLabProjectPayload.model_validate_json)
        _require_matching_repository(metadata.path_with_namespace, repository)
        logger.debug(
            "GitLab project metadata fetched",
            **log_context,
            provider_repository_id=str(metadata.id),
            has_readme_url=metadata.readme_url is not None,
            topic_count=len(metadata.topics),
        )

        readme_result, languages, release = await fetch_repository_resources(
            self._fetch_readme(root, repository, metadata.readme_url, metadata.default_branch),
            fetch_languages(self._http, root, self._headers),
            self._fetch_release(root, repository),
        )
        readme, normalized_readme_url = readme_result or (None, None)

        links = await to_thread(
            build_repository_links,
            repository.url,
            release_url=release.url if release else None,
            homepage=None,
            readme=readme,
            readme_url=normalized_readme_url,
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

    async def _fetch_readme(
        self, root: str, repository: RepositoryRef, readme_url: str | None, default_branch: str | None
    ) -> tuple[str, str] | None:
        file_path = _readme_path(readme_url, default_branch=default_branch)
        if file_path is None:
            logger.debug("GitLab README path unavailable")
            return None

        response = await self._http.get_optional(
            f"{root}/repository/files/{quote(file_path, safe='')}/raw", headers=self._headers, params={"ref": "HEAD"}
        )
        if response is None:
            logger.debug("GitLab README raw file not found")
            return None

        readme = response.text
        logger.debug("GitLab README fetched", readme_bytes=len(readme.encode()))
        normalized_readme_url = f"{repository.url}/-/blob/HEAD/{quote(file_path, safe='/')}"
        return readme, normalized_readme_url

    async def _fetch_release(self, root: str, repository: RepositoryRef) -> RepositoryRelease | None:
        response = await self._http.get_optional(f"{root}/releases/permalink/latest", headers=self._headers)
        if response is None:
            logger.debug("GitLab latest release not found")
            return None

        release = await self._http.parse(response, _GitLabReleasePayload.model_validate_json)
        release_url = f"{repository.url}/-/releases/{quote(release.tag_name, safe='')}"
        logger.debug("GitLab latest release fetched", release_tag=release.tag_name)
        return RepositoryRelease(
            name=release.name or release.tag_name,
            tag=release.tag_name,
            url=release_url,
            description=release.description,
        )


def _readme_path(readme_url: str | None, *, default_branch: str | None) -> str | None:
    if not readme_url or not default_branch:
        return None

    parsed = urlsplit(readme_url)
    if parsed.scheme.casefold() != "https" or (parsed.hostname or "").casefold() != "gitlab.com":
        return None
    marker = f"/-/blob/{quote(default_branch, safe='')}/"
    _, found, file_path = parsed.path.partition(marker)
    if not found:
        return None

    try:
        return require_repository_path(unquote(file_path))
    except ValueError:
        return None


def _license_name(license_data: _GitLabLicensePayload | None) -> str | None:
    if license_data is None:
        return None

    return license_data.nickname or license_data.key or license_data.name


def _require_matching_repository(path_with_namespace: str, repository: RepositoryRef) -> None:
    if path_with_namespace.casefold() == repository.full_name.casefold():
        return
    msg = "GitLab returned metadata for a different repository"
    raise ExternalServiceError(msg)
