# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from bot.integrations.repositories.errors import RepositoryClientError
from bot.integrations.repositories.models import (
    RepositoryAuthor,
    RepositoryInfo,
    RepositoryPlatform,
    RepositoryReadme,
    parse_http_url,
    parse_optional_http_url,
)
from bot.logging import get_logger

from .base import BaseRepositoryFetcher

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from .base import JSONObject

logger = get_logger(__name__)

_GITLAB_API: Final[str] = "https://gitlab.com/api/v4"
_DEFAULT_USER_AGENT: Final[str] = "AndroidRepoBot/1.0"
_PROJECT_ENDPOINT_DETAILS: Final[str] = "Unexpected GitLab project payload"
_README_CANDIDATES: Final[tuple[str, ...]] = ("README.md", "README.MD", "README.rst", "README")


@dataclass(frozen=True, slots=True, kw_only=True)
class GitLabConfig:
    token: str | None = None
    user_agent: str = _DEFAULT_USER_AGENT


def _encode_project_path(owner: str, name: str) -> str:
    segments = [segment.strip("/") for segment in (owner, name) if segment]
    raw_path = "/".join(segment for segment in segments if segment)
    base_path = raw_path or name.strip("/")
    return quote(base_path, safe="")


class GitLabRepositoryFetcher(BaseRepositoryFetcher):
    __slots__ = ("_config",)

    def __init__(
        self, *, token: str | None = None, session: ClientSession, user_agent: str = _DEFAULT_USER_AGENT
    ) -> None:
        super().__init__(session=session)
        self._config = GitLabConfig(token=token, user_agent=user_agent)

    @property
    def _platform_name(self) -> str:
        return "GitLab"

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": self._config.user_agent}
        if self._config.token:
            headers["PRIVATE-TOKEN"] = self._config.token
        return headers

    async def fetch_repository(self, owner: str, name: str) -> RepositoryInfo:
        await logger.ainfo("Fetching GitLab repository", owner=owner, name=name)

        project_path = _encode_project_path(owner, name)
        project_data = await self._request_object(
            f"{_GITLAB_API}/projects/{project_path}", details=_PROJECT_ENDPOINT_DETAILS
        )
        if project_data is None:
            raise RepositoryClientError(self._platform_name, details="GitLab project payload is missing")

        readme = await self._fetch_readme(project_data)
        repository = self._build_repository_info(project_data, readme=readme)

        await logger.ainfo(
            "GitLab repository fetched successfully",
            owner=owner,
            name=name,
            full_name=repository.full_name,
            has_readme=repository.has_readme,
            tags_count=len(repository.tags),
        )

        return repository

    async def _fetch_readme(self, project_data: JSONObject) -> RepositoryReadme | None:
        branch = self._string_value(project_data.get("default_branch"))
        if branch is None:
            await logger.adebug("No default branch found", project_id=project_data.get("id"))
            return None

        project_id = self._identifier_value(project_data.get("id"))
        web_url = self._string_value(project_data.get("web_url"))

        tasks = {
            asyncio.create_task(
                self._fetch_readme_candidate(project_id=project_id, branch=branch, web_url=web_url, filename=filename),
                name=f"gitlab-readme:{filename}",
            )
            for filename in _README_CANDIDATES
        }

        try:
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    try:
                        readme = task.result()
                    except RepositoryClientError as error:
                        await self._cancel_tasks(pending)
                        await logger.aerror("Failed to fetch GitLab README", project_id=project_id, error=str(error))
                        raise

                    if readme is None:
                        continue

                    await self._cancel_tasks(pending)
                    return readme
        finally:
            await self._cancel_tasks(tasks)

        await logger.adebug("No README found", project_id=project_id)
        return None

    async def _fetch_readme_candidate(
        self, *, project_id: int | str, branch: str, web_url: str | None, filename: str
    ) -> RepositoryReadme | None:
        await logger.adebug("Trying README file", project_id=project_id, filename=filename)

        content = await self._request_text(
            f"{_GITLAB_API}/projects/{project_id}/repository/files/{quote(filename, safe='')}/raw",
            params={"ref": branch},
            ignore_404=True,
        )

        if content is None:
            return None

        sanitized_content = self._sanitize_readme_content(content)
        if not sanitized_content:
            await logger.adebug("README content empty after sanitization", project_id=project_id, filename=filename)
            return None

        await logger.adebug(
            "README found", project_id=project_id, filename=filename, content_length=len(sanitized_content)
        )

        return RepositoryReadme(
            path=filename,
            content=sanitized_content,
            source_url=parse_optional_http_url(f"{web_url}/-/raw/{branch}/{filename}" if web_url else None),
        )

    @staticmethod
    async def _cancel_tasks(tasks: set[asyncio.Task[RepositoryReadme | None]]) -> None:
        if not tasks:
            return

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    def _build_repository_info(self, payload: JSONObject, *, readme: RepositoryReadme | None) -> RepositoryInfo:
        repository_id = self._identifier_value(payload.get("id"))
        name = self._require_string(payload, "name", source="project")
        full_name = self._string_value(payload.get("path_with_namespace")) or self._require_string(
            payload, "path", source="project"
        )
        web_url = self._require_string(payload, "web_url", source="project")

        return RepositoryInfo(
            platform=RepositoryPlatform.GITLAB,
            id=repository_id,
            name=name,
            full_name=full_name,
            description=self._string_value(payload.get("description")),
            web_url=parse_http_url(web_url),
            tags=self._extract_topics(payload),
            readme=readme,
            author=self._extract_author(payload),
        )

    def _extract_author(self, payload: JSONObject) -> RepositoryAuthor:
        namespace = self._mapping_value(payload.get("namespace"))
        owner_data = self._mapping_value(payload.get("owner")) or namespace
        author_id = self._identifier_value(
            owner_data.get("id"),
            fallback=self._identifier_value(
                namespace.get("id"), fallback=self._identifier_value(payload.get("creator_id"))
            ),
        )

        username = (
            self._string_value(owner_data.get("username"))
            or self._string_value(owner_data.get("path"))
            or self._string_value(namespace.get("full_path"))
            or self._string_value(payload.get("path_with_namespace"))
            or self._require_string(payload, "path", source="project")
        )
        display_name = self._string_value(owner_data.get("name")) or self._string_value(namespace.get("name"))
        url = self._string_value(owner_data.get("web_url")) or self._string_value(namespace.get("web_url"))

        if url is None and (full_path := self._string_value(namespace.get("full_path"))):
            url = f"https://gitlab.com/{full_path}"

        return RepositoryAuthor(
            id=author_id, username=username, display_name=display_name, url=parse_optional_http_url(url)
        )

    def _extract_topics(self, payload: JSONObject) -> list[str]:
        topics = payload.get("topics")
        if isinstance(topics, list):
            extracted_topics = self._unique_strings(topics)
            if extracted_topics:
                return extracted_topics

        legacy_topics = payload.get("tag_list")
        if isinstance(legacy_topics, list):
            return self._unique_strings(legacy_topics)

        return []
