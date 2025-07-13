# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

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


class BaseRepositoryClient(ABC):
    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> BaseRepositoryClient:
        if self._owns_session:
            self._session = aiohttp.ClientSession()
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
    @abstractmethod
    def api_base(self) -> str: ...

    @property
    @abstractmethod
    def platform_name(self) -> str: ...

    @abstractmethod
    def _parse_url(self, url: str) -> tuple[str, str]: ...

    @abstractmethod
    def _build_headers(self) -> dict[str, str]: ...

    @abstractmethod
    async def _get_repository_data(self, owner: str, repo: str) -> Repository: ...

    @abstractmethod
    async def _fetch_readme(self, *args: Any) -> str | None: ...

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
            BaseRepositoryClient._validate_repository_url(url)
            parsed = urlparse(url.strip())
            return parsed.netloc in {"github.com", "gitlab.com"}
        except Exception:
            return False

    async def get_basic_repository_data(self, repository_url: str) -> Repository:
        self._validate_repository_url(repository_url)
        owner, repo = self._parse_url(repository_url)
        return await self._get_repository_data(owner, repo)

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

        repository = await self._get_repository_data(owner, repo)
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

    def _validate_platform_url(self, url: str) -> None:
        parsed = urlparse(url.strip())
        if parsed.netloc != self.platform_name:
            msg = f"Not a {self.platform_name} URL"
            raise ValueError(msg)

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) < 2:
            msg = f"Invalid {self.platform_name} repository URL"
            raise ValueError(msg)
