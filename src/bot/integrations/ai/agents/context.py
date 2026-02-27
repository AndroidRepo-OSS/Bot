# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bot.integrations.ai.models import RepositorySummary
    from bot.integrations.repositories.models import RepositoryInfo


def render_repository_section(repository: RepositoryInfo, *, include_author: bool = False) -> list[str]:
    lines = ["## Repository Data", "", f"**Name:** {repository.name}", f"**Full Name:** {repository.full_name}"]

    if include_author:
        lines.append(f"**Author:** {repository.author.label}")

    lines.extend([
        f"**Platform:** {repository.platform.value}",
        f"**Description:** {repository.description or 'Not provided'}",
    ])

    if repository.tags:
        lines.append(f"**Topics:** {', '.join(repository.tags)}")

    lines.append(f"**Repository URL:** {repository.web_url}")
    return lines


def render_summary_section(summary: RepositorySummary) -> list[str]:
    parts = [
        "## Current Preview",
        f"**Project Name:** {summary.project_name}",
        f"**Enhanced Description:** {summary.enhanced_description}",
    ]

    append_bullet_block(parts, "**Key Features:**", summary.key_features, empty="- (none provided)")
    append_bullet_block(
        parts,
        "**Important Links:**",
        (f"{link.label}: {link.url}" for link in summary.important_links),
        empty="- (none provided)",
    )
    append_bullet_block(parts, "**Tags:**", (tag.value for tag in summary.tags), empty="- (none provided)")

    return parts


def append_bullet_block(parts: list[str], title: str, items: Iterable[str], *, empty: str | None = None) -> None:
    values = [item for item in items if item]
    parts.extend(["", title])

    if values:
        parts.extend(f"- {item}" for item in values)
        return

    if empty is not None:
        parts.append(empty)


def append_text_block(parts: list[str], title: str, body: str, *, intro: str | None = None) -> None:
    if not body:
        return

    parts.extend(["", title])

    if intro:
        parts.extend([intro, ""])

    parts.append(body)
