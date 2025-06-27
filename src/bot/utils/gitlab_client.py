# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from urllib.parse import urlparse

from .base_client import BaseRepositoryClient
from .models import GitLabRepository

logger = logging.getLogger(__name__)


class GitLabClient(BaseRepositoryClient):
    @property
    def api_base(self) -> str:
        return "https://gitlab.com/api/v4"

    @property
    def platform_name(self) -> str:
        return "gitlab.com"

    def _parse_url(self, url: str) -> tuple[str, str]:
        self._validate_platform_url(url)
        parsed = urlparse(url.strip())
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        return path_parts[0], path_parts[1]

    @staticmethod
    def _build_headers() -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "AndroidRepo-Bot/1.0",
        }

    async def _get_repository_data(self, owner: str, repo: str) -> GitLabRepository:
        project_path = f"{owner}/{repo}"
        encoded_path = project_path.replace("/", "%2F")
        url = f"{self.api_base}/projects/{encoded_path}"
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
        readme_files = ["README.md", "README.rst", "README.txt", "README"]
        branches = ["main", "master"]

        for readme_file in readme_files:
            for branch in branches:
                try:
                    url = (
                        f"{self.api_base}/projects/{project_id}/repository/files/"
                        f"{readme_file}?ref={branch}"
                    )
                    readme_data = await self._fetch_json(url)

                    if content := readme_data.get("content"):
                        return self._decode_base64_content(content)
                except Exception:
                    continue

        logger.warning("Failed to fetch README for project %s", project_id)
        return None
