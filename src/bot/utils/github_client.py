# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
import logging
from urllib.parse import urlparse

import aiohttp

from .cache import repository_cache
from .models import (
    EnhancedRepositoryData,
    GitHubRepository,
)
from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
README_MAX_LENGTH = 1000


class GitHubClient:
    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._should_close_session = session is None

    async def __aenter__(self) -> GitHubClient:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._should_close_session and self._session:
            await self._session.close()

    @staticmethod
    def _parse_github_url(url: str) -> tuple[str, str]:
        parsed = urlparse(url.strip())

        if parsed.netloc != "github.com":
            msg = "Not a GitHub URL"
            raise ValueError(msg)

        path_parts = parsed.path.strip("/").split("/")

        if len(path_parts) < 2:
            msg = "Invalid GitHub repository URL"
            raise ValueError(msg)

        owner, repo = path_parts[0], path_parts[1]

        if not owner or not repo:
            msg = "Invalid GitHub repository URL"
            raise ValueError(msg)

        return owner, repo

    @staticmethod
    def _truncate_readme(content: str) -> str:
        if len(content) <= README_MAX_LENGTH:
            return content

        truncated = content[:README_MAX_LENGTH].rsplit(" ", 1)[0]
        return f"{truncated}..."

    async def _fetch_json(self, url: str) -> dict:
        if not self._session:
            msg = "Session not initialized"
            raise RuntimeError(msg)

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AndroidRepo-Bot/1.0",
        }

        async with self._session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

    async def _get_repository_data(self, owner: str, repo: str) -> GitHubRepository:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        data = await self._fetch_json(url)

        readme_content = None
        try:
            readme_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme"
            readme_data = await self._fetch_json(readme_url)

            if readme_data.get("content"):
                decoded_content = base64.b64decode(readme_data["content"]).decode("utf-8")
                readme_content = self._truncate_readme(decoded_content)
        except Exception as e:
            logger.warning("Failed to fetch README for %s/%s: %s", owner, repo, e)

        return GitHubRepository(
            name=data["name"],
            full_name=data["full_name"],
            owner=data["owner"]["login"],
            description=data.get("description"),
            url=data["html_url"],
            topics=data.get("topics", []),
            readme_content=readme_content,
        )

    async def get_enhanced_repository_data(
        self, github_url: str, openai_api_key: str, openai_base_url: str | None = None
    ) -> EnhancedRepositoryData:
        cached_data = repository_cache.get(github_url)
        if cached_data:
            logger.info("Using cached data for repository: %s", github_url)
            return cached_data

        owner, repo = self._parse_github_url(github_url)

        logger.info("Fetching GitHub repository data: %s/%s", owner, repo)

        repository = await self._get_repository_data(owner, repo)

        try:
            async with OpenAIClient(api_key=openai_api_key, base_url=openai_base_url) as ai_client:
                ai_content = await ai_client.enhance_repository_content(
                    repo_name=repository.name,
                    description=repository.description,
                    readme_content=repository.readme_content,
                    topics=repository.topics,
                )

                logger.info("Successfully enhanced content for %s", repository.name)

        except Exception as e:
            logger.warning("Failed to enhance content for %s: %s", repository.name, e)
            ai_content = None

        enhanced_data = EnhancedRepositoryData(
            repository=repository,
            ai_content=ai_content,
        )

        repository_cache.set(github_url, enhanced_data)

        return enhanced_data
