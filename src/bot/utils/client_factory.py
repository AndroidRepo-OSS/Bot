# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from urllib.parse import urlparse

import aiohttp

from .base_client import BaseRepositoryClient, UnsupportedPlatformError
from .github_client import GitHubClient
from .gitlab_client import GitLabClient


def get_repository_client(
    url: str, session: aiohttp.ClientSession | None = None
) -> BaseRepositoryClient:
    parsed = urlparse(url.strip())
    netloc = parsed.netloc

    if netloc == "github.com":
        return GitHubClient.get_client_for_url(url, session)
    if netloc == "gitlab.com":
        return GitLabClient.get_client_for_url(url, session)

    msg = f"Unsupported platform: {netloc}"
    raise UnsupportedPlatformError(msg)


def is_valid_repository_url(url: str) -> bool:
    try:
        BaseRepositoryClient._validate_repository_url(url)
        parsed = urlparse(url.strip())
        return parsed.netloc in {"github.com", "gitlab.com"}
    except Exception:
        return False
