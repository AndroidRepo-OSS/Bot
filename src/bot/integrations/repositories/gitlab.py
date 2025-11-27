# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from anyio import create_task_group

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from pydantic import AnyHttpUrl

from .base import BaseRepositoryFetcher
from .errors import RepositoryClientError
from .models import RepositoryAuthor, RepositoryInfo, RepositoryPlatform, RepositoryReadme

_GITLAB_API = "https://gitlab.com/api/v4"


class GitLabRepositoryFetcher(BaseRepositoryFetcher):
    __slots__ = ("_token", "_user_agent")

    def __init__(
        self, *, token: str | None = None, session: ClientSession, user_agent: str = "AndroidRepoBot/1.0"
    ) -> None:
        super().__init__(session=session)
        self._token = token
        self._user_agent = user_agent

    @property
    def _platform_name(self) -> str:
        return "GitLab"

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": self._user_agent}
        if self._token:
            headers["PRIVATE-TOKEN"] = self._token
        return headers

    async def fetch_repository(self, owner: str, name: str) -> RepositoryInfo:
        project_path = self._encode_project_path(owner, name)
        project_data: dict[str, Any] | None = None
        tags: list[str] = []
        readme: RepositoryReadme | None = None

        async def load_project_and_readme() -> None:
            nonlocal project_data, readme
            project_raw = await self._make_request(f"{_GITLAB_API}/projects/{project_path}")
            if not isinstance(project_raw, dict):
                raise RepositoryClientError(self._platform_name, details="Unexpected project payload")
            project_data = cast("dict[str, Any]", project_raw)
            readme = await self._fetch_readme(project_data)

        async def load_tags() -> None:
            nonlocal tags
            tags = await self._fetch_tags(project_path)

        try:
            async with create_task_group() as task_group:
                task_group.start_soon(load_project_and_readme)
                task_group.start_soon(load_tags)
        except* RepositoryClientError as exc_group:
            first = cast("RepositoryClientError", exc_group.exceptions[0])
            raise first

        assert project_data is not None

        author = self._build_author(project_data)
        return RepositoryInfo(
            platform=RepositoryPlatform.GITLAB,
            id=project_data["id"],
            name=project_data["name"],
            full_name=project_data.get("path_with_namespace", project_data["name"]),
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
            return []
        if not isinstance(data, list):
            raise RepositoryClientError(self._platform_name, details="Unexpected tags payload")

        tag_names: list[str] = []
        for tag in data:
            if not isinstance(tag, dict):
                continue
            name = tag.get("name")
            if isinstance(name, str):
                tag_names.append(name)
        return list(dict.fromkeys(tag_names))

    async def _fetch_readme(self, project_data: dict[str, Any]) -> RepositoryReadme | None:
        branch = project_data.get("default_branch")
        if not branch:
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
                content = await self._make_request(
                    f"{_GITLAB_API}/projects/{project_id}/repository/files/{file_path}/raw",
                    params={"ref": branch},
                    return_json=False,
                    ignore_404=True,
                )
                if content is None:
                    return
                if not isinstance(content, str):
                    raise RepositoryClientError(self._platform_name, details="Unexpected README payload")

                source_url = f"{web_url}/-/raw/{branch}/{filename}" if web_url else None
                readme = RepositoryReadme(
                    path=filename, content=content, source_url=cast("AnyHttpUrl | None", source_url)
                )
                task_group.cancel_scope.cancel()

            for filename in ("README.md", "README.MD", "README.rst", "README"):
                task_group.start_soon(try_readme, filename)

        if readme is not None:
            return readme

        return None

    @staticmethod
    def _build_author(project_data: dict[str, Any]) -> RepositoryAuthor:
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

    @staticmethod
    def _encode_project_path(owner: str, name: str) -> str:
        segments = [segment.strip("/") for segment in (owner, name) if segment]
        raw_path = "/".join(segment for segment in segments if segment)
        base = raw_path or name.strip("/")
        return quote(base, safe="")
