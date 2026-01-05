# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from bot.integrations.repositories import RepositoryPlatform

if TYPE_CHECKING:
    from bot.integrations.repositories import BaseRepositoryFetcher, GitHubRepositoryFetcher, GitLabRepositoryFetcher


class RepositoryUrlParseError(RuntimeError):
    __slots__ = ("reason", "url")

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"Invalid repository URL '{url}': {reason}")
        self.url = url
        self.reason = reason


@dataclass(slots=True, frozen=True)
class RepositoryLocator:
    platform: RepositoryPlatform
    owner: str
    name: str


def parse_repository_url(raw_url: str) -> RepositoryLocator:
    if not raw_url or not raw_url.strip():
        raise RepositoryUrlParseError(raw_url, "Value cannot be empty")

    candidate = raw_url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise RepositoryUrlParseError(raw_url, "Unsupported URL scheme. Use http or https.")

    host = (parsed.hostname or "").lower()
    platform = _detect_platform(host)

    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments or len(segments) < 2:
        raise RepositoryUrlParseError(raw_url, "Expected /owner/repo structure")

    owner, name = _split_owner_repo(platform, segments)

    return RepositoryLocator(platform=platform, owner=owner, name=name)


def select_fetcher(
    locator: RepositoryLocator, *, github_fetcher: GitHubRepositoryFetcher, gitlab_fetcher: GitLabRepositoryFetcher
) -> BaseRepositoryFetcher:
    if locator.platform is RepositoryPlatform.GITHUB:
        return github_fetcher
    if locator.platform is RepositoryPlatform.GITLAB:
        return gitlab_fetcher
    raise RepositoryUrlParseError(locator.name, f"Unsupported platform: {locator.platform.value}")


def _detect_platform(hostname: str) -> RepositoryPlatform:
    if hostname.endswith("github.com"):
        return RepositoryPlatform.GITHUB
    if hostname.endswith("gitlab.com"):
        return RepositoryPlatform.GITLAB
    raise RepositoryUrlParseError(hostname, "Only github.com and gitlab.com URLs are supported")


def _split_owner_repo(platform: RepositoryPlatform, segments: list[str]) -> tuple[str, str]:
    if platform is RepositoryPlatform.GITHUB:
        owner = segments[0]
        name = segments[1]
        return owner, _normalize_repo_name(name)

    filtered: list[str] = []
    for segment in segments:
        if segment == "-":
            break
        filtered.append(segment)

    if len(filtered) < 2:
        raise RepositoryUrlParseError("/".join(segments), "Unable to determine project path")

    owner = "/".join(filtered[:-1])
    name = _normalize_repo_name(filtered[-1])
    return owner, name


def _normalize_repo_name(name: str) -> str:
    return name.removesuffix(".git")
