# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp

from .github_client import GitHubClient
from .gitlab_client import GitLabClient
from .models import EnhancedRepositoryData

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)


class UnsupportedPlatformError(ValueError):
    pass


class InvalidRepositoryURLError(ValueError):
    pass


class Platform(Enum):
    GITHUB = "github.com"
    GITLAB = "gitlab.com"

    @classmethod
    def from_url(cls, url: str) -> Platform:
        netloc = urlparse(url.strip()).netloc

        for platform in cls:
            if netloc == platform.value:
                return platform

        msg = f"Unsupported platform: {netloc}"
        raise UnsupportedPlatformError(msg)


def _validate_repository_url(url: str) -> None:
    try:
        parsed = urlparse(url.strip())

        if not parsed.netloc:
            msg = "URL must have a valid domain"
            raise InvalidRepositoryURLError(msg)

        if parsed.netloc not in {platform.value for platform in Platform}:
            msg = f"Unsupported platform: {parsed.netloc}"
            raise UnsupportedPlatformError(msg)

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) < 2:
            msg = "URL must contain owner and repository name"
            raise InvalidRepositoryURLError(msg)

    except (AttributeError, TypeError) as e:
        msg = f"Invalid URL format: {e}"
        raise InvalidRepositoryURLError(msg) from e


class RepositoryClient:
    def __init__(self, *, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> RepositoryClient:
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

    @staticmethod
    def is_valid_repository_url(url: str) -> bool:
        try:
            _validate_repository_url(url)
            return True
        except (InvalidRepositoryURLError, UnsupportedPlatformError):
            return False

    async def get_enhanced_repository_data(
        self, repository_url: str, openai_api_key: str, *, openai_base_url: str | None = None
    ) -> EnhancedRepositoryData:
        _validate_repository_url(repository_url)

        if not self._session:
            msg = "Client session not initialized. Use 'async with RepositoryClient()' pattern."
            raise RuntimeError(msg)

        platform = Platform.from_url(repository_url)
        client_class = GitHubClient if platform == Platform.GITHUB else GitLabClient

        async with client_class(self._session) as client:
            return await client.get_enhanced_repository_data(
                repository_url, openai_api_key, openai_base_url
            )
