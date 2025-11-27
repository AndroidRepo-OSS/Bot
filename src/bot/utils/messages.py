# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.utils.formatting import Bold, Italic, Text, TextLink

if TYPE_CHECKING:
    from bot.integrations.ai import ImportantLink, RepositorySummary
    from bot.integrations.repositories import RepositoryInfo

BULLET = "•"


def render_post_caption(repository: RepositoryInfo, summary: RepositorySummary) -> str:
    parts: list[Text | str] = []

    title = summary.project_name.strip() or repository.name
    parts.append(Bold(title))

    description = summary.enhanced_description.strip() or (repository.description or "")
    if description:
        parts.extend(("\n\n", Italic(description), "\n"))

    if summary.key_features:
        parts.extend(("\n", Bold("✨ Key Features:")))
        for feature in summary.key_features:
            cleaned = feature.strip()
            if not cleaned:
                continue
            parts.append(f"\n{BULLET} {cleaned}")
        parts.append("\n")

    links_section = _build_links_section(repository, summary.important_links)
    if links_section:
        parts.extend(links_section)

    content = Text(*parts)
    return content.as_html()


def _build_links_section(repository: RepositoryInfo, important_links: list[ImportantLink]) -> list[Text | str]:
    pairs: list[tuple[str, str]] = []

    pairs.append((f"{repository.platform.value.title()} Repository", str(repository.web_url)))

    pairs.extend((link.label, str(link.url)) for link in important_links)

    seen: set[str] = set()
    parts: list[Text | str] = ["\n", Bold("🔗 Links:")]
    for label, url in pairs:
        if not url or url in seen:
            continue
        seen.add(url)
        parts.extend(("\n", f"{BULLET} ", TextLink(label, url=url)))

    return parts
