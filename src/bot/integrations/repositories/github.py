# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from binascii import Error as BinasciiError
from typing import TYPE_CHECKING, Any, cast

from anyio import create_task_group, to_thread

if TYPE_CHECKING:
    from aiohttp import ClientSession

from .base import BaseRepositoryFetcher
from .errors import RepositoryClientError
from .models import RepositoryAuthor, RepositoryInfo, RepositoryPlatform, RepositoryReadme

_GITHUB_API = "https://api.github.com"


class GitHubRepositoryFetcher(BaseRepositoryFetcher):
    __slots__ = ("_token", "_user_agent")

    def __init__(
        self, *, token: str | None = None, session: ClientSession, user_agent: str = "AndroidRepoBot/1.0"
    ) -> None:
        super().__init__(session=session)
        self._token = token
        self._user_agent = user_agent

    @property
    def _platform_name(self) -> str:
        return "GitHub"

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self._user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def fetch_repository(self, owner: str, name: str) -> RepositoryInfo:
        repo_data: dict[str, Any] | None = None
        readme: RepositoryReadme | None = None

        async def load_repository() -> None:
            nonlocal repo_data
            response = await self._make_request(f"{_GITHUB_API}/repos/{owner}/{name}")
            if not isinstance(response, dict):
                raise RepositoryClientError(self._platform_name, details="Unexpected repository payload")
            repo_data = cast("dict[str, Any]", response)

        async def load_readme() -> None:
            nonlocal readme
            readme = await self._fetch_readme(owner, name)

        try:
            async with create_task_group() as task_group:
                task_group.start_soon(load_repository)
                task_group.start_soon(load_readme)
        except* RepositoryClientError as exc_group:
            first = cast("RepositoryClientError", exc_group.exceptions[0])
            raise first

        assert repo_data is not None

        owner_data = repo_data.get("owner", {})
        author = RepositoryAuthor(
            id=owner_data.get("id", repo_data.get("owner_id", 0)),
            username=owner_data.get("login") or owner_data.get("name") or owner,
            display_name=owner_data.get("name"),
            url=owner_data.get("html_url"),
        )

        tags = list(dict.fromkeys(tag for tag in (repo_data.get("topics") or []) if isinstance(tag, str)))

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
            return None
        if not isinstance(data, dict):
            raise RepositoryClientError(self._platform_name, details="Unexpected README payload")

        encoded_content = data.get("content")
        if not encoded_content:
            return None

        encoding = data.get("encoding", "base64")
        content = encoded_content
        if encoding.lower() == "base64":
            content = await self._decode_readme_content(encoded_content)

        return RepositoryReadme(
            path=data.get("path", "README.md"),
            content=content,
            source_url=data.get("download_url") or data.get("html_url"),
        )

    async def _decode_readme_content(self, payload: str) -> str:
        def decode_with_validation() -> str:
            buffer = base64.b64decode(payload, validate=True)
            return buffer.decode("utf-8", errors="replace")

        def decode_without_validation() -> str:
            buffer = base64.b64decode(payload, validate=False)
            return buffer.decode("utf-8", errors="replace")

        try:
            return await to_thread.run_sync(decode_with_validation)
        except BinasciiError:
            pass
        except UnicodeDecodeError as exc:
            raise RepositoryClientError(self._platform_name, details="Unable to decode README content") from exc
        try:
            return await to_thread.run_sync(decode_without_validation)
        except (BinasciiError, ValueError, UnicodeDecodeError) as exc:
            raise RepositoryClientError(self._platform_name, details="Unable to decode README content") from exc
