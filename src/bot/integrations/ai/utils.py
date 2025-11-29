# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from bot.logging import get_logger

if TYPE_CHECKING:
    from re import Pattern

    from bot.integrations.repositories.models import RepositoryInfo

logger = get_logger(__name__)

_URL_PATTERN: Final[Pattern[str]] = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_MAX_README_CHARS: Final[int] = 16000


def extract_readme(repository: RepositoryInfo) -> str:
    if not repository.readme or not repository.readme.content:
        logger.debug("No README content available", repository=repository.full_name)
        return ""

    content = repository.readme.content.strip()
    original_length = len(content)

    if original_length <= _MAX_README_CHARS:
        logger.debug("README extracted without truncation", repository=repository.full_name, length=original_length)
        return content

    logger.debug(
        "README truncated due to size limit",
        repository=repository.full_name,
        original_length=original_length,
        truncated_length=_MAX_README_CHARS,
    )
    return f"{content[:_MAX_README_CHARS].rstrip()}..."


def extract_links(text: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    if not text:
        logger.debug("No text provided for link extraction")
        return results

    for match in _URL_PATTERN.findall(text):
        url = match.rstrip(".,);]\"' ")
        if url and url not in seen:
            seen.add(url)
            results.append(url)

    logger.debug("Links extracted from text", links_count=len(results))
    return results
