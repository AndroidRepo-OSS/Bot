import base64
import binascii
from asyncio import to_thread
from time import perf_counter
from types import MappingProxyType
from typing import TYPE_CHECKING

import structlog
from pydantic import Field

from androidrepo_bot.repositories.http import (
    ApiClient,
    ProviderModel,
    WebUrl,
    fetch_languages,
    fetch_repository_resources,
)
from androidrepo_bot.repositories.links import build_repository_links
from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef, RepositoryRelease, require_web_url

if TYPE_CHECKING:
    from collections.abc import Mapping

    import aiohttp

logger = structlog.get_logger(__name__)

_DEFAULT_HEADERS: Mapping[str, str] = MappingProxyType({
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
})


class GitHubLicense(ProviderModel):
    spdx_id: str | None = None
    name: str | None = None


class GitHubRepository(ProviderModel):
    id: int
    node_id: str | None = None
    name: str = Field(min_length=1)
    description: str | None = None
    html_url: WebUrl
    homepage: str | None = None
    topics: tuple[str, ...] = Field(default_factory=tuple)
    license: GitHubLicense | None = None


class GitHubReadme(ProviderModel):
    content: str
    encoding: str
    html_url: WebUrl


class GitHubRelease(ProviderModel):
    name: str | None = None
    tag_name: str = Field(min_length=1)
    html_url: WebUrl
    body: str | None = None


class GitHubClient:
    def __init__(self, *, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._api = ApiClient(client=session, provider_name="GitHub")
        self._headers = dict(_DEFAULT_HEADERS)
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def fetch(self, repository: RepositoryRef) -> RepositoryDetails:
        started_at = perf_counter()
        log_context = {"provider": repository.provider.value, "repository": repository.full_name}
        logger.debug("GitHub repository metadata fetch started", **log_context)
        root = f"https://api.github.com/repos/{repository.full_name}"
        response = await self._api.get(root, headers=self._headers)
        metadata = await self._api.parse_model(GitHubRepository, response)
        logger.debug(
            "GitHub repository metadata fetched",
            **log_context,
            provider_repository_id=metadata.node_id or str(metadata.id),
            has_homepage=bool(metadata.homepage),
            topic_count=len(metadata.topics),
        )

        readme_result, languages, release = await fetch_repository_resources(
            self._fetch_readme(root), fetch_languages(self._api, root, self._headers), self._fetch_release(root)
        )
        readme, readme_url = readme_result or (None, None)

        homepage = _optional_web_url(metadata.homepage)
        links = await to_thread(
            build_repository_links,
            metadata.html_url,
            release_url=release.url if release else None,
            homepage=homepage,
            readme=readme,
            readme_url=readme_url,
        )
        details = RepositoryDetails(
            ref=repository,
            provider_repository_id=metadata.node_id or str(metadata.id),
            display_name=metadata.name,
            description=metadata.description,
            readme=readme,
            languages=languages,
            license=_license_name(metadata.license),
            topics=metadata.topics,
            homepage=homepage,
            release=release,
            links=links,
        )
        logger.debug(
            "GitHub repository evidence normalized",
            **log_context,
            duration_seconds=perf_counter() - started_at,
            has_readme=readme is not None,
            has_release=release is not None,
            language_count=len(languages),
            link_count=len(links),
        )
        return details

    async def _fetch_readme(self, root: str) -> tuple[str, str] | None:
        response = await self._api.get_optional(f"{root}/readme", headers=self._headers)
        if response is None:
            logger.debug("GitHub README not found")
            return None

        readme = await self._api.parse_model(GitHubReadme, response)
        if readme.encoding.casefold() != "base64":
            logger.warning("GitHub README ignored because encoding is unsupported", encoding=readme.encoding)
            return None

        content = await to_thread(_decode_readme_content, readme.content)
        if content is None:
            logger.warning("GitHub README ignored because base64 decoding failed")
            return None

        logger.debug("GitHub README fetched", readme_bytes=len(content.encode()))
        return content, readme.html_url

    async def _fetch_release(self, root: str) -> RepositoryRelease | None:
        response = await self._api.get_optional(f"{root}/releases/latest", headers=self._headers)
        if response is None:
            logger.debug("GitHub latest release not found")
            return None

        release = await self._api.parse_model(GitHubRelease, response)
        logger.debug("GitHub latest release fetched", release_tag=release.tag_name)
        return RepositoryRelease(
            name=release.name or release.tag_name, tag=release.tag_name, url=release.html_url, description=release.body
        )


def _license_name(license_data: GitHubLicense | None) -> str | None:
    if license_data is None:
        return None

    if license_data.spdx_id and license_data.spdx_id != "NOASSERTION":
        return license_data.spdx_id

    return license_data.name


def _decode_readme_content(content: str) -> str | None:
    try:
        encoded_content = "".join(content.split())
        return base64.b64decode(encoded_content, validate=True).decode("utf-8", errors="replace")
    except binascii.Error, ValueError:
        return None


def _optional_web_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return require_web_url(value)
    except ValueError:
        return None
