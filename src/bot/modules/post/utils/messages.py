# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.utils.formatting import Bold, Italic, TextLink, as_list, as_marked_list

if TYPE_CHECKING:
    from aiogram.utils.formatting import Text

    from bot.integrations.ai import ImportantLink, RepositorySummary
    from bot.integrations.repositories import RepositoryInfo

    type TextNode = str | Text


def render_post_caption(repository: RepositoryInfo, summary: RepositorySummary) -> str:
    title = summary.project_name.strip() or repository.name
    description = summary.enhanced_description.strip() or repository.description or ""

    sections: list[TextNode] = [Bold(title)]

    if description:
        sections.extend(("", Italic(description)))

    if summary.key_features:
        features = [feature.strip() for feature in summary.key_features if feature.strip()]
        if features:
            sections.extend(("", as_marked_list(Bold("✨ Key Features:"), *features, marker="• ")))

    links = _build_links_section(repository, summary.important_links)
    if links:
        sections.extend(("", links))

    if summary.tags:
        seen: set[str] = set()
        tags: list[str] = []

        for tag in summary.tags:
            value = tag.value if hasattr(tag, "value") else str(tag)
            cleaned = value.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            tags.append(f"#{cleaned}")

        if tags:
            tag_line = Bold("🏷 Tags: ") + " ".join(tags)
            sections.extend(("", tag_line))

    return as_list(*sections).as_html()


def _build_links_section(repository: RepositoryInfo, important_links: list[ImportantLink]) -> Text | None:
    pairs: list[tuple[str, str]] = [
        (f"{repository.platform.value.title()} Repository", str(repository.web_url)),
        *((link.label, str(link.url)) for link in important_links),
    ]

    seen: set[str] = set()
    link_nodes: list[TextNode] = []

    for label, url in pairs:
        if not url or url in seen:
            continue
        seen.add(url)
        link_nodes.append(TextLink(label, url=url))

    if not link_nodes:
        return None

    return as_marked_list(Bold("🔗 Links:"), *link_nodes, marker="• ")
