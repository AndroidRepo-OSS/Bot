# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
import logging
from urllib.parse import urlparse

import aiohttp

from .models import EnhancedRepositoryData, GitLabRepository
from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)

GITLAB_API_BASE = "https://gitlab.com/api/v4"


class GitLabClient:
    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> GitLabClient:
        if self._owns_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    @staticmethod
    def _parse_gitlab_url(url: str) -> tuple[str, str]:
        parsed = urlparse(url.strip())

        if parsed.netloc != "gitlab.com":
            msg = "Not a GitLab URL"
            raise ValueError(msg)

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]

        if len(path_parts) < 2:
            msg = "Invalid GitLab repository URL"
            raise ValueError(msg)

        return path_parts[0], path_parts[1]

    async def _fetch_json(self, url: str) -> dict:
        if not self._session:
            msg = "Session not initialized"
            raise RuntimeError(msg)

        headers = {
            "Accept": "application/json",
            "User-Agent": "AndroidRepo-Bot/1.0",
        }

        async with self._session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

    async def _get_repository_data(self, owner: str, repo: str) -> GitLabRepository:
        project_path = f"{owner}/{repo}"
        encoded_path = project_path.replace("/", "%2F")
        url = f"{GITLAB_API_BASE}/projects/{encoded_path}"
        data = await self._fetch_json(url)

        readme_content = await self._fetch_readme(data["id"])

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

    async def _fetch_readme(self, project_id: int) -> str | None:
        try:
            readme_files = ["README.md", "README.rst", "README.txt", "README"]

            for readme_file in readme_files:
                try:
                    url = (
                        f"{GITLAB_API_BASE}/projects/{project_id}/repository/files/"
                        f"{readme_file}?ref=main"
                    )
                    readme_data = await self._fetch_json(url)

                    if content := readme_data.get("content"):
                        return base64.b64decode(content).decode("utf-8")
                except Exception:
                    continue

            url = f"{GITLAB_API_BASE}/projects/{project_id}/repository/files/README.md?ref=master"
            readme_data = await self._fetch_json(url)

            if content := readme_data.get("content"):
                return base64.b64decode(content).decode("utf-8")

        except Exception as e:
            logger.warning("Failed to fetch README for project %s: %s", project_id, e)

        return None

    async def get_enhanced_repository_data(
        self, gitlab_url: str, openai_api_key: str, openai_base_url: str | None = None
    ) -> EnhancedRepositoryData:
        owner, repo = self._parse_gitlab_url(gitlab_url)
        logger.info("Fetching GitLab repository data: %s/%s", owner, repo)

        repository = await self._get_repository_data(owner, repo)
        ai_content = await self._get_ai_content(repository, openai_api_key, openai_base_url)

        return EnhancedRepositoryData(
            repository=repository,
            ai_content=ai_content,
        )

    @staticmethod
    async def _get_ai_content(
        repository: GitLabRepository, openai_api_key: str, openai_base_url: str | None
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
