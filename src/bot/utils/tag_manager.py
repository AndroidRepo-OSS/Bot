# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging

from bot.database.operations import filter_and_save_tags, get_standard_tags, update_tag_usage

logger = logging.getLogger(__name__)


async def process_ai_generated_tags(ai_tags: list[str]) -> list[str]:
    if not ai_tags:
        return []

    normalized_tags = [tag.lower().strip() for tag in ai_tags if tag.strip()]

    await update_tag_usage(normalized_tags)

    return await filter_and_save_tags(normalized_tags)


async def get_tags_for_ai_context() -> set[str]:
    return await get_standard_tags()
