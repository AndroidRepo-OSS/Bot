# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging

from bot.database.operations import filter_and_save_tags, get_all_tags

logger = logging.getLogger(__name__)

DEFAULT_TAGS: set[str] = {
    "communication",
    "productivity",
    "utilities",
    "customization",
    "privacy",
    "material_design",
    "root",
    "magisk_module",
}


async def process_ai_generated_tags(ai_tags: list[str]) -> list[str]:
    if not ai_tags:
        return []

    normalized_tags = [tag.lower().strip() for tag in ai_tags if tag.strip()]

    if len(normalized_tags) < 5:
        logger.warning(
            "AI generated only %d tags, expected 5-7. Tags: %s",
            len(normalized_tags),
            normalized_tags,
        )
    elif len(normalized_tags) > 7:
        logger.warning(
            "AI generated %d tags, expected 5-7. Keeping first 7 tags: %s",
            len(normalized_tags),
            normalized_tags[:7],
        )
        normalized_tags = normalized_tags[:7]

    return await filter_and_save_tags(normalized_tags)


async def get_tags_for_ai_context() -> set[str]:
    existing = await get_all_tags()
    if not existing:
        return set(DEFAULT_TAGS)
    return existing | DEFAULT_TAGS
