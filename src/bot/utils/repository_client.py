# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp

from .enums import Platform
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


def _validate_repository_url(url: str) -> None:
    try:
        parsed = urlparse(url.strip())

        if not parsed.netloc:
            msg = "URL must have a valid domain"
            raise InvalidRepositoryURLError(msg)

        try:
            Platform.from_url(url)
        except ValueError as e:
            raise UnsupportedPlatformError(str(e)) from e

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

    def _get_client(self, platform: Platform):
        if not self._session:
            msg = "Client session not initialized. Use 'async with RepositoryClient()' pattern."
            raise RuntimeError(msg)

        client_map = {
            Platform.GITHUB: GitHubClient,
            Platform.GITLAB: GitLabClient,
        }
        return client_map[platform](self._session)

    async def get_basic_repository_data(self, repository_url: str):
        _validate_repository_url(repository_url)
        platform = Platform.from_url(repository_url)

        async with self._get_client(platform) as client:
            owner, repo = client._parse_url(repository_url)
            return await client._get_repository_data(owner, repo)

    async def get_enhanced_repository_data(
        self, repository_url: str, openai_api_key: str, *, openai_base_url: str | None = None
    ) -> EnhancedRepositoryData:
        _validate_repository_url(repository_url)
        platform = Platform.from_url(repository_url)

        async with self._get_client(platform) as client:
            return await client.get_enhanced_repository_data(
                repository_url, openai_api_key, openai_base_url
            )
