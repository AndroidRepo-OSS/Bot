# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import asyncio
import base64
from binascii import Error as BinasciiError
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from bot.integrations.repositories.errors import RepositoryClientError
from bot.integrations.repositories.models import RepositoryAuthor, RepositoryInfo, RepositoryPlatform, RepositoryReadme
from bot.logging import get_logger

from .base import BaseRepositoryFetcher

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from .base import JSONObject

logger = get_logger(__name__)

_GITHUB_API: Final[str] = "https://api.github.com"
_GITHUB_API_VERSION: Final[str] = "2022-11-28"
_DEFAULT_USER_AGENT: Final[str] = "AndroidRepoBot/1.0"
_README_ENDPOINT_DETAILS: Final[str] = "Unexpected GitHub README payload"
_REPOSITORY_ENDPOINT_DETAILS: Final[str] = "Unexpected GitHub repository payload"
_README_DECODE_ERROR: Final[str] = "Unable to decode GitHub README content"


@dataclass(frozen=True, slots=True, kw_only=True)
class GitHubConfig:
    token: str | None = None
    user_agent: str = _DEFAULT_USER_AGENT
    api_version: str = _GITHUB_API_VERSION


def _normalize_base64_payload(payload: str) -> str:
    return "".join(payload.split())


def _decode_base64_payload(payload: str) -> str:
    normalized_payload = _normalize_base64_payload(payload)

    def decode_strict() -> str:
        buffer = base64.b64decode(normalized_payload, validate=True)
        return buffer.decode("utf-8", errors="replace")

    def decode_lenient() -> str:
        buffer = base64.b64decode(normalized_payload, validate=False)
        return buffer.decode("utf-8", errors="replace")

    try:
        return decode_strict()
    except BinasciiError:
        logger.debug("Base64 validation failed, retrying without validation")
    except UnicodeDecodeError as exc:
        logger.exception("Failed to decode README content", error=str(exc))
        msg = "GitHub"
        raise RepositoryClientError(msg, details=_README_DECODE_ERROR) from exc

    try:
        return decode_lenient()
    except (BinasciiError, ValueError, UnicodeDecodeError) as exc:
        logger.exception("Failed to decode README content (fallback)", error=str(exc))
        msg = "GitHub"
        raise RepositoryClientError(msg, details=_README_DECODE_ERROR) from exc


class GitHubRepositoryFetcher(BaseRepositoryFetcher):
    __slots__ = ("_config",)

    def __init__(
        self, *, token: str | None = None, session: ClientSession, user_agent: str = _DEFAULT_USER_AGENT
    ) -> None:
        super().__init__(session=session)
        self._config = GitHubConfig(token=token, user_agent=user_agent)

    @property
    def _platform_name(self) -> str:
        return "GitHub"

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self._config.user_agent,
            "X-GitHub-Api-Version": self._config.api_version,
        }

        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"

        return headers

    async def fetch_repository(self, owner: str, name: str) -> RepositoryInfo:
        await logger.ainfo("Fetching GitHub repository", owner=owner, name=name)

        try:
            async with asyncio.TaskGroup() as task_group:
                repository_task = task_group.create_task(
                    self._request_object(f"{_GITHUB_API}/repos/{owner}/{name}", details=_REPOSITORY_ENDPOINT_DETAILS)
                )
                readme_task = task_group.create_task(self._fetch_readme(owner, name))
        except* RepositoryClientError as exc_group:
            error = self._unwrap_client_error(exc_group)
            await logger.aerror("Failed to fetch GitHub repository", owner=owner, name=name, error=str(error))
            raise error

        repository_payload = repository_task.result()
        readme = readme_task.result()

        if repository_payload is None:
            raise RepositoryClientError(self._platform_name, details="GitHub repository payload is missing")

        repository = self._build_repository_info(repository_payload, readme=readme, fallback_owner=owner)

        await logger.ainfo(
            "GitHub repository fetched successfully",
            owner=owner,
            name=name,
            full_name=repository.full_name,
            has_readme=repository.has_readme,
            tags_count=len(repository.tags),
        )

        return repository

    async def _fetch_readme(self, owner: str, name: str) -> RepositoryReadme | None:
        data = await self._request_object(
            f"{_GITHUB_API}/repos/{owner}/{name}/readme", ignore_404=True, details=_README_ENDPOINT_DETAILS
        )
        if data is None:
            await logger.adebug("No README found", owner=owner, name=name)
            return None

        encoded_content = self._string_value(data.get("content"))
        if encoded_content is None:
            await logger.adebug("README has no content", owner=owner, name=name)
            return None

        encoding = (self._string_value(data.get("encoding")) or "base64").casefold()
        content = encoded_content if encoding != "base64" else _decode_base64_payload(encoded_content)
        sanitized_content = self._sanitize_readme_content(content)
        if not sanitized_content:
            await logger.adebug("README content empty after sanitization", owner=owner, name=name)
            return None

        readme_path = self._string_value(data.get("path")) or "README.md"
        source_url = self._string_value(data.get("download_url")) or self._string_value(data.get("html_url"))

        await logger.adebug(
            "README fetched successfully",
            owner=owner,
            name=name,
            path=readme_path,
            content_length=len(sanitized_content),
        )

        return RepositoryReadme(path=readme_path, content=sanitized_content, source_url=source_url)

    def _build_repository_info(
        self, payload: JSONObject, *, readme: RepositoryReadme | None, fallback_owner: str
    ) -> RepositoryInfo:
        repository_id = self._identifier_value(payload.get("id"))
        name = self._require_string(payload, "name", source="repository")
        full_name = self._require_string(payload, "full_name", source="repository")
        web_url = self._require_string(payload, "html_url", source="repository")

        return RepositoryInfo(
            platform=RepositoryPlatform.GITHUB,
            id=repository_id,
            name=name,
            full_name=full_name,
            description=self._string_value(payload.get("description")),
            web_url=web_url,
            tags=self._extract_topics(payload),
            readme=readme,
            author=self._extract_author(payload, fallback_username=fallback_owner),
        )

    def _extract_author(self, payload: JSONObject, *, fallback_username: str) -> RepositoryAuthor:
        owner_data = self._mapping_value(payload.get("owner"))
        owner_id = self._identifier_value(
            owner_data.get("id"), fallback=self._identifier_value(payload.get("owner_id"))
        )
        username = (
            self._string_value(owner_data.get("login"))
            or self._string_value(owner_data.get("name"))
            or fallback_username
        )

        return RepositoryAuthor(
            id=owner_id,
            username=username,
            display_name=self._string_value(owner_data.get("name")),
            url=self._string_value(owner_data.get("html_url")),
        )

    def _extract_topics(self, payload: JSONObject) -> list[str]:
        topics = payload.get("topics")
        if not isinstance(topics, list):
            return []

        return self._unique_strings(topics)
