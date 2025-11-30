# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast
from urllib.parse import quote

from anyio import create_task_group

from bot.integrations.repositories.errors import RepositoryClientError
from bot.integrations.repositories.models import RepositoryAuthor, RepositoryInfo, RepositoryPlatform, RepositoryReadme
from bot.logging import get_logger

from .base import BaseRepositoryFetcher

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from pydantic import AnyHttpUrl

logger = get_logger(__name__)

_GITLAB_API: Final[str] = "https://gitlab.com/api/v4"
_DEFAULT_USER_AGENT: Final[str] = "AndroidRepoBot/1.0"
_README_CANDIDATES: Final[tuple[str, ...]] = ("README.md", "README.MD", "README.rst", "README")


@dataclass(frozen=True, slots=True)
class GitLabConfig:
    token: str | None = None
    user_agent: str = _DEFAULT_USER_AGENT


def _encode_project_path(owner: str, name: str) -> str:
    segments = [segment.strip("/") for segment in (owner, name) if segment]
    raw_path = "/".join(segment for segment in segments if segment)
    base = raw_path or name.strip("/")
    return quote(base, safe="")


def _build_author_from_project(project_data: dict[str, Any]) -> RepositoryAuthor:
    namespace = project_data.get("namespace") or {}
    owner_data = project_data.get("owner") or namespace

    author_id = owner_data.get("id") or namespace.get("id") or project_data.get("creator_id", 0)

    username = (
        owner_data.get("username")
        or owner_data.get("path")
        or namespace.get("full_path")
        or project_data.get("path_with_namespace", project_data["path"])
    )

    display_name = owner_data.get("name") or namespace.get("name")
    url = owner_data.get("web_url") or namespace.get("web_url")

    if url is None and namespace.get("full_path"):
        url = f"https://gitlab.com/{namespace['full_path']}"

    return RepositoryAuthor(
        id=author_id, username=username, display_name=display_name, url=cast("AnyHttpUrl | None", url)
    )


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
        project_data: dict[str, Any] | None = None
        tags: list[str] = []
        readme: RepositoryReadme | None = None

        async def load_project_and_readme() -> None:
            nonlocal project_data, readme
            await logger.adebug("Loading project metadata", owner=owner, name=name)
            project_raw = await self._make_request(f"{_GITLAB_API}/projects/{project_path}")

            if not isinstance(project_raw, dict):
                msg = "Unexpected project payload"
                raise RepositoryClientError(self._platform_name, details=msg)

            project_data = cast("dict[str, Any]", project_raw)

            await logger.adebug("Loading README", owner=owner, name=name)
            readme = await self._fetch_readme(project_data)

        async def load_tags() -> None:
            nonlocal tags
            await logger.adebug("Loading tags", owner=owner, name=name)
            tags = await self._fetch_tags(project_path)

        try:
            async with create_task_group() as task_group:
                task_group.start_soon(load_project_and_readme)
                task_group.start_soon(load_tags)
        except* RepositoryClientError as exc_group:
            first = cast("RepositoryClientError", exc_group.exceptions[0])
            await logger.aerror("Failed to fetch GitLab repository", owner=owner, name=name, error=str(first))
            raise first

        assert project_data is not None

        author = _build_author_from_project(project_data)
        full_name = project_data.get("path_with_namespace", project_data["name"])

        await logger.ainfo(
            "GitLab repository fetched successfully",
            owner=owner,
            name=name,
            full_name=full_name,
            has_readme=readme is not None,
            tags_count=len(tags),
        )

        return RepositoryInfo(
            platform=RepositoryPlatform.GITLAB,
            id=project_data["id"],
            name=project_data["name"],
            full_name=full_name,
            description=project_data.get("description"),
            web_url=project_data["web_url"],
            tags=tags,
            readme=readme,
            author=author,
        )

    async def _fetch_tags(self, project_id: int | str) -> list[str]:
        data = await self._make_request(
            f"{_GITLAB_API}/projects/{project_id}/repository/tags", params={"per_page": 100}, ignore_404=True
        )

        if not data:
            await logger.adebug("No tags found", project_id=project_id)
            return []

        if not isinstance(data, list):
            msg = "Unexpected tags payload"
            raise RepositoryClientError(self._platform_name, details=msg)

        tag_names: list[str] = []
        for tag in data:
            if not isinstance(tag, dict):
                continue
            name = tag.get("name")
            if isinstance(name, str):
                tag_names.append(name)

        unique_tags = list(dict.fromkeys(tag_names))
        await logger.adebug("Tags fetched", project_id=project_id, tags_count=len(unique_tags))
        return unique_tags

    async def _fetch_readme(self, project_data: dict[str, Any]) -> RepositoryReadme | None:
        branch = project_data.get("default_branch")
        if not branch:
            await logger.adebug("No default branch found", project_id=project_data.get("id"))
            return None

        project_id = project_data["id"]
        web_url = project_data.get("web_url")

        readme: RepositoryReadme | None = None

        async with create_task_group() as task_group:

            async def try_readme(filename: str) -> None:
                nonlocal readme
                if readme is not None:
                    return

                file_path = quote(filename, safe="")
                await logger.adebug("Trying README file", project_id=project_id, filename=filename)

                content = await self._make_request(
                    f"{_GITLAB_API}/projects/{project_id}/repository/files/{file_path}/raw",
                    params={"ref": branch},
                    return_json=False,
                    ignore_404=True,
                )

                if content is None:
                    return

                if not isinstance(content, str):
                    msg = "Unexpected README payload"
                    raise RepositoryClientError(self._platform_name, details=msg)

                sanitized_content = self._sanitize_readme_content(content)

                source_url = f"{web_url}/-/raw/{branch}/{filename}" if web_url else None
                readme = RepositoryReadme(
                    path=filename, content=sanitized_content, source_url=cast("AnyHttpUrl | None", source_url)
                )

                await logger.adebug(
                    "README found", project_id=project_id, filename=filename, content_length=len(sanitized_content)
                )
                task_group.cancel_scope.cancel()

            for filename in _README_CANDIDATES:
                task_group.start_soon(try_readme, filename)

        if readme is not None:
            return readme

        await logger.adebug("No README found", project_id=project_id)
        return None
