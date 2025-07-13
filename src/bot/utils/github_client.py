# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from urllib.parse import urlparse

import aiohttp

from .base_client import BaseRepositoryClient, UnsupportedPlatformError
from .models import GitHubRepository

logger = logging.getLogger(__name__)


class GitHubClient(BaseRepositoryClient):
    @property
    def api_base(self) -> str:
        return "https://api.github.com"

    @property
    def platform_name(self) -> str:
        return "github.com"

    @staticmethod
    def is_github_url(url: str) -> bool:
        try:
            GitHubClient._validate_repository_url(url)
            parsed = urlparse(url.strip())
            return parsed.netloc == "github.com"
        except Exception:
            return False

    @staticmethod
    def get_client_for_url(url: str, session: aiohttp.ClientSession | None = None) -> GitHubClient:
        if not GitHubClient.is_github_url(url):
            msg = f"Not a GitHub URL: {url}"
            raise UnsupportedPlatformError(msg)
        return GitHubClient(session)

    def _parse_url(self, url: str) -> tuple[str, str]:
        self._validate_platform_url(url)
        parsed = urlparse(url.strip())
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        return path_parts[0], path_parts[1]

    @staticmethod
    def _build_headers() -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AndroidRepo-Bot/1.0",
        }

    async def _get_repository_data(self, owner: str, repo: str) -> GitHubRepository:
        url = f"{self.api_base}/repos/{owner}/{repo}"
        data = await self._fetch_json(url)
        readme_content = await self._fetch_readme(owner, repo)

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

    async def _fetch_readme(self, owner: str, repo: str) -> str | None:
        try:
            readme_url = f"{self.api_base}/repos/{owner}/{repo}/readme"
            readme_data = await self._fetch_json(readme_url)

            if content := readme_data.get("content"):
                return self._decode_base64_content(content)
        except Exception as e:
            logger.warning("Failed to fetch README for %s/%s: %s", owner, repo, e)

        return None
