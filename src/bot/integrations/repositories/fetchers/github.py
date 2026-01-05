# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from binascii import Error as BinasciiError
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from anyio import create_task_group, to_thread

from bot.integrations.repositories.errors import RepositoryClientError
from bot.integrations.repositories.models import RepositoryAuthor, RepositoryInfo, RepositoryPlatform, RepositoryReadme
from bot.logging import get_logger

from .base import BaseRepositoryFetcher

if TYPE_CHECKING:
    from aiohttp import ClientSession

logger = get_logger(__name__)

_GITHUB_API: Final[str] = "https://api.github.com"
_GITHUB_API_VERSION: Final[str] = "2022-11-28"
_DEFAULT_USER_AGENT: Final[str] = "AndroidRepoBot/1.0"


@dataclass(frozen=True, slots=True)
class GitHubConfig:
    token: str | None = None
    user_agent: str = _DEFAULT_USER_AGENT
    api_version: str = _GITHUB_API_VERSION


async def _decode_base64(payload: str) -> str:
    def decode_strict() -> str:
        buffer = base64.b64decode(payload, validate=True)
        return buffer.decode("utf-8", errors="replace")

    def decode_lenient() -> str:
        buffer = base64.b64decode(payload, validate=False)
        return buffer.decode("utf-8", errors="replace")

    try:
        return await to_thread.run_sync(decode_strict)
    except BinasciiError:
        await logger.adebug("Base64 validation failed, retrying without validation")
    except UnicodeDecodeError as exc:
        await logger.aerror("Failed to decode content", error=str(exc))
        msg = "Unable to decode content"
        msg = "GitHub"
        raise RepositoryClientError(msg, details=msg) from exc

    try:
        return await to_thread.run_sync(decode_lenient)
    except (BinasciiError, ValueError, UnicodeDecodeError) as exc:
        await logger.aerror("Failed to decode content (fallback)", error=str(exc))
        msg = "Unable to decode content"
        msg = "GitHub"
        raise RepositoryClientError(msg, details=msg) from exc


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

        repo_data: dict[str, Any] | None = None
        readme: RepositoryReadme | None = None

        async def load_repository() -> None:
            nonlocal repo_data
            await logger.adebug("Loading repository metadata", owner=owner, name=name)
            response = await self._make_request(f"{_GITHUB_API}/repos/{owner}/{name}")
            if not isinstance(response, dict):
                raise RepositoryClientError(self._platform_name, details="Unexpected repository payload")

            repo_data = response

        async def load_readme() -> None:
            nonlocal readme
            await logger.adebug("Loading README", owner=owner, name=name)
            readme = await self._fetch_readme(owner, name)

        try:
            async with create_task_group() as task_group:
                task_group.start_soon(load_repository)
                task_group.start_soon(load_readme)
        except* RepositoryClientError as exc_group:
            first = cast("RepositoryClientError", exc_group.exceptions[0])
            await logger.aerror("Failed to fetch GitHub repository", owner=owner, name=name, error=str(first))
            raise first

        assert repo_data is not None

        author = self._extract_author(repo_data, owner)
        tags = self._extract_tags(repo_data)

        await logger.ainfo(
            "GitHub repository fetched successfully",
            owner=owner,
            name=name,
            full_name=repo_data["full_name"],
            has_readme=readme is not None,
            tags_count=len(tags),
        )

        return RepositoryInfo(
            platform=RepositoryPlatform.GITHUB,
            id=repo_data["id"],
            name=repo_data["name"],
            full_name=repo_data["full_name"],
            description=repo_data.get("description"),
            web_url=repo_data["html_url"],
            tags=tags,
            readme=readme,
            author=author,
        )

    async def _fetch_readme(self, owner: str, name: str) -> RepositoryReadme | None:
        data = await self._make_request(f"{_GITHUB_API}/repos/{owner}/{name}/readme", ignore_404=True)
        if not data:
            await logger.adebug("No README found", owner=owner, name=name)
            return None

        if not isinstance(data, dict):
            raise RepositoryClientError(self._platform_name, details="Unexpected README payload")

        encoded_content = data.get("content")
        if not encoded_content:
            await logger.adebug("README has no content", owner=owner, name=name)
            return None

        encoding = data.get("encoding", "base64")
        content = encoded_content

        if encoding.lower() == "base64":
            await logger.adebug("Decoding base64 README content", owner=owner, name=name)
            content = await _decode_base64(encoded_content)

        content = self._sanitize_readme_content(content)

        readme_path = data.get("path", "README.md")
        await logger.adebug(
            "README fetched successfully", owner=owner, name=name, path=readme_path, content_length=len(content)
        )

        return RepositoryReadme(
            path=readme_path, content=content, source_url=data.get("download_url") or data.get("html_url")
        )

    @staticmethod
    def _extract_author(repo_data: dict[str, Any], fallback_username: str) -> RepositoryAuthor:
        owner_data = repo_data.get("owner", {})
        return RepositoryAuthor(
            id=owner_data.get("id", repo_data.get("owner_id", 0)),
            username=owner_data.get("login") or owner_data.get("name") or fallback_username,
            display_name=owner_data.get("name"),
            url=owner_data.get("html_url"),
        )

    @staticmethod
    def _extract_tags(repo_data: dict[str, Any]) -> list[str]:
        topics = repo_data.get("topics") or []
        return list(dict.fromkeys(tag for tag in topics if isinstance(tag, str)))
