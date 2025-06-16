# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
import logging
from urllib.parse import urlparse

import aiohttp

from .cache import repository_cache
from .models import EnhancedRepositoryData, GitHubRepository
from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session

    async def __aenter__(self) -> GitHubClient:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session:
            await self._session.close()

    @staticmethod
    def _parse_github_url(url: str) -> tuple[str, str]:
        parsed = urlparse(url.strip())

        if parsed.netloc != "github.com":
            msg = "Not a GitHub URL"
            raise ValueError(msg)

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]

        if len(path_parts) < 2:
            msg = "Invalid GitHub repository URL"
            raise ValueError(msg)

        return path_parts[0], path_parts[1]

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

        readme_content = await self._fetch_readme(owner, repo)

        return GitHubRepository(
            name=data["name"],
            full_name=data["full_name"],
            owner=data["owner"]["login"],
            description=data.get("description"),
            url=data["html_url"],
            topics=data.get("topics", []),
            readme_content=readme_content,
        )

    async def _fetch_readme(self, owner: str, repo: str) -> str | None:
        try:
            readme_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme"
            readme_data = await self._fetch_json(readme_url)

            if content := readme_data.get("content"):
                return base64.b64decode(content).decode("utf-8")
        except Exception as e:
            logger.warning("Failed to fetch README for %s/%s: %s", owner, repo, e)

        return None

    async def get_enhanced_repository_data(
        self, github_url: str, openai_api_key: str, openai_base_url: str | None = None
    ) -> EnhancedRepositoryData:
        if cached_data := repository_cache.get(github_url):
            logger.info("Using cached data for repository: %s", github_url)
            return cached_data

        owner, repo = self._parse_github_url(github_url)
        logger.info("Fetching GitHub repository data: %s/%s", owner, repo)

        repository = await self._get_repository_data(owner, repo)
        ai_content = await self._get_ai_content(repository, openai_api_key, openai_base_url)

        enhanced_data = EnhancedRepositoryData(
            repository=repository,
            ai_content=ai_content,
        )

        repository_cache.set(github_url, enhanced_data)
        return enhanced_data

    @staticmethod
    async def _get_ai_content(
        repository: GitHubRepository, openai_api_key: str, openai_base_url: str | None
    ):
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
