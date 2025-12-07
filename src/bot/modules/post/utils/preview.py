# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InputMediaPhoto
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder
from anyio import to_thread

from bot.modules.post.utils.models import SubmissionAction, SubmissionCallback
from bot.services import BannerGenerator

if TYPE_CHECKING:
    from aiogram import Bot

    from bot.integrations.ai import RepositorySummary
    from bot.integrations.nasa import NasaApodService
    from bot.integrations.repositories import RepositoryInfo
    from bot.modules.post.utils.models import SubmissionData


_banner_generator = BannerGenerator()


async def render_banner(
    repository: RepositoryInfo, summary: RepositorySummary, nasa_apod_service: NasaApodService
) -> bytes:
    background = await nasa_apod_service.fetch_image()
    return await to_thread.run_sync(_banner_generator.generate, summary.project_name or repository.name, background)


async def build_debug_link(bot: Bot | None, payload: str) -> str | None:
    if not bot:
        return None
    with suppress(TelegramBadRequest):
        return await create_start_link(bot, payload, encode=True)
    return None


def build_preview_keyboard(submission_id: str, debug_url: str | None) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for text, action in (
        ("🚀 Publish", SubmissionAction.PUBLISH),
        ("✏️ Edit", SubmissionAction.EDIT),
        ("❌ Cancel", SubmissionAction.CANCEL),
    ):
        builder.button(text=text, callback_data=SubmissionCallback(action=action, submission_id=submission_id))

    if debug_url:
        builder.button(text="🔍 Inspect Data", url=debug_url)
    builder.adjust(*(2, 1, 1) if debug_url else (2, 1))
    return builder


async def update_preview_message(bot: Bot, submission: SubmissionData, banner_bytes: bytes, caption: str) -> None:
    photo = BufferedInputFile(banner_bytes, filename=f"{submission.submission_id}.png")
    media = InputMediaPhoto(media=photo, caption=caption)
    keyboard = build_preview_keyboard(submission.submission_id, submission.debug_url)

    await bot.edit_message_media(
        chat_id=submission.preview_chat_id,
        message_id=submission.preview_message_id,
        media=media,
        reply_markup=keyboard.as_markup(),
    )
