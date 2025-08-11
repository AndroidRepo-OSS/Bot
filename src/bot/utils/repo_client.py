# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import quote, urlparse

import aiohttp

from .models import EnhancedRepositoryData, GitHubRepository, GitLabRepository
from .openai_client import OpenAIClient

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)

Repository = GitHubRepository | GitLabRepository


class UnsupportedPlatformError(ValueError):
    pass


class InvalidRepositoryURLError(ValueError):
    pass


class RepositoryClient:
    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None
        self._platform_name: str | None = None
        self._api_base: str | None = None
        self._cache_key: tuple[str, str] | None = None
        self._cache_repo: Repository | None = None

    async def __aenter__(self) -> Self:
        if self._owns_session:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    @property
    def api_base(self) -> str:
        if self._api_base:
            return self._api_base
        return "https://api.github.com"

    @property
    def platform_name(self) -> str:
        return self._platform_name or "unknown"

    @staticmethod
    def _validate_repository_url(url: str) -> None:
        try:
            parsed = urlparse(url.strip())

            if not parsed.netloc:
                msg = "URL must have a valid domain"
                raise InvalidRepositoryURLError(msg)

            path_parts = [part for part in parsed.path.strip("/").split("/") if part]
            if len(path_parts) < 2:
                msg = "URL must contain owner and repository name"
                raise InvalidRepositoryURLError(msg)

        except (AttributeError, TypeError) as e:
            msg = f"Invalid URL format: {e}"
            raise InvalidRepositoryURLError(msg) from e

    @staticmethod
    def is_valid_repository_url(url: str) -> bool:
        try:
            RepositoryClient._validate_repository_url(url)
            parsed = urlparse(url.strip())
            return parsed.netloc in {"github.com", "gitlab.com"}
        except Exception:
            return False

    def _parse_url(self, url: str) -> tuple[str, str]:
        self._validate_repository_url(url)
        parsed = urlparse(url.strip())
        platform_api_map = {
            "github.com": "https://api.github.com",
            "gitlab.com": "https://gitlab.com/api/v4",
        }
        api_base = platform_api_map.get(parsed.netloc)
        if not api_base:
            msg = f"Unsupported platform: {parsed.netloc}"
            raise UnsupportedPlatformError(msg)
        self._platform_name = parsed.netloc
        self._api_base = api_base

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        return path_parts[0], path_parts[1]

    def _build_headers(self) -> dict[str, str]:
        accept = (
            "application/vnd.github+json"
            if self.platform_name == "github.com"
            else "application/json"
        )
        return {
            "Accept": accept,
            "User-Agent": f"AndroidRepo-Bot/1.0 ({self.platform_name})",
        }

    async def get_basic_repository_data(self, repository_url: str) -> Repository:
        self._validate_repository_url(repository_url)
        owner, repo = self._parse_url(repository_url)
        repository = await self._get_repository_data(owner, repo)
        self._cache_key = (owner, repo)
        self._cache_repo = repository
        return repository

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        if not self._session:
            msg = "Session not initialized"
            raise RuntimeError(msg)

        headers = self._build_headers()
        async with self._session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

    @staticmethod
    def _decode_base64_content(content: str) -> str:
        return base64.b64decode(content).decode("utf-8")

    async def get_enhanced_repository_data(
        self, repository_url: str, openai_api_key: str, openai_base_url: str | None = None
    ) -> EnhancedRepositoryData:
        owner, repo = self._parse_url(repository_url)
        logger.info("Fetching %s repository data: %s/%s", self.platform_name, owner, repo)

        if self._cache_key == (owner, repo) and self._cache_repo is not None:
            repository = self._cache_repo
        else:
            repository = await self._get_repository_data(owner, repo)
            self._cache_key = (owner, repo)
            self._cache_repo = repository
        ai_content = await self._get_ai_content(repository, openai_api_key, openai_base_url)

        return EnhancedRepositoryData(repository=repository, ai_content=ai_content)

    @staticmethod
    async def _get_ai_content(
        repository: Repository, openai_api_key: str, openai_base_url: str | None
    ) -> Any:
        try:
            async with OpenAIClient(api_key=openai_api_key, base_url=openai_base_url) as ai_client:
                ai_content = await ai_client.enhance_repository_content(
                    repo_name=repository.name,
                    description=repository.description,
                    readme_content=repository.readme_content,
                    topics=repository.topics,
                )
                logger.info("Successfully enhanced content for %s", repository.name)
                return ai_content
        except Exception as e:
            logger.warning("Failed to enhance content for %s: %s", repository.name, e)
            return None

    async def _get_repository_data(self, owner: str, repo: str) -> Repository:
        if self.platform_name == "github.com":
            url = f"{self.api_base}/repos/{owner}/{repo}"
            data = await self._fetch_json(url)
            readme_content = await self._fetch_github_readme(owner, repo)

            return GitHubRepository(
                id=data["id"],
                name=data["name"],
                full_name=data["full_name"],
                owner=data["owner"]["login"],
                description=data.get("description"),
                url=data["html_url"],
                topics=data.get("topics", []),
                readme_content=readme_content,
            )

        if self.platform_name == "gitlab.com":
            project_path = f"{owner}/{repo}"
            encoded_path = quote(project_path, safe="")
            url = f"{self.api_base}/projects/{encoded_path}"
            data = await self._fetch_json(url)
            readme_content = await self._fetch_gitlab_readme(data["id"])

            return GitLabRepository(
                id=data["id"],
                name=data["name"],
                full_name=data["path_with_namespace"],
                owner=data["namespace"]["name"],
                description=data.get("description"),
                url=data["web_url"],
                topics=data.get("topics", []),
                readme_content=readme_content,
            )

        msg = f"Unsupported platform: {self.platform_name}"
        raise UnsupportedPlatformError(msg)

    async def _fetch_github_readme(self, owner: str, repo: str) -> str | None:
        try:
            readme_url = f"{self.api_base}/repos/{owner}/{repo}/readme"
            readme_data = await self._fetch_json(readme_url)
            content = readme_data.get("content")
            if content:
                return self._decode_base64_content(content)
            return None
        except Exception as e:
            logger.warning("Failed to fetch README: %s", e)
            return None

    async def _fetch_gitlab_readme(self, project_id: int) -> str | None:
        readme_files = ["README.md", "README.rst", "README.txt", "README"]
        branches = ["main", "master"]
        for readme_file in readme_files:
            for branch in branches:
                try:
                    url = (
                        f"{self.api_base}/projects/{project_id}/repository/files/"
                        f"{quote(readme_file, safe='')}?ref={branch}"
                    )
                    readme_data = await self._fetch_json(url)
                    content = readme_data.get("content")
                    if content:
                        return self._decode_base64_content(content)
                except Exception:
                    continue
        logger.warning(
            "Failed to fetch README for project %s",
            project_id,
        )
        return None
