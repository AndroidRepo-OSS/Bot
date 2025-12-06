# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router, flags
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile

from bot.logging import get_logger
from bot.modules.post.utils.models import SubmissionAction, SubmissionCallback
from bot.modules.post.utils.session import cleanup_messages, validate_submission

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery

    from bot.config import BotSettings
    from bot.modules.post.utils.models import SubmissionData
    from bot.services import PreviewDebugRegistry, TelegramLogger


router = Router(name="post-publish")
logger = get_logger(__name__)


@router.callback_query(SubmissionCallback.filter(F.action == SubmissionAction.PUBLISH))
@flags.callback_answer(text="Published in @AndroidRepo!")
async def handle_publish_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    preview_registry: PreviewDebugRegistry,
    settings: BotSettings,
    telegram_logger: TelegramLogger,
) -> None:
    if not (submission := await validate_submission(callback, callback_data, state)):
        return

    if not (banner_bytes := submission.banner_bytes):
        await callback.answer("Preview data is corrupted. Please start over.", show_alert=True)
        preview_registry.discard(submission.submission_id)
        await state.clear()
        return

    preview_entry = preview_registry.get(submission.submission_id)
    repository = preview_entry.repository if preview_entry else None

    photo = BufferedInputFile(banner_bytes, filename=f"post-{submission.submission_id}.png")
    try:
        await bot.send_photo(chat_id=settings.post_channel_id, photo=photo, caption=submission.caption)
    except TelegramRetryAfter as exc:
        await logger.awarning("Telegram rate limit hit while publishing", retry_after=exc.retry_after)
        await callback.answer(f"Rate limited. Try again in {exc.retry_after} seconds.", show_alert=True)
        return

    if repository and callback.from_user:
        await telegram_logger.log_post_published(callback.from_user, repository)

    await _finalize_submission(bot, state, preview_registry, submission, callback)


@router.callback_query(SubmissionCallback.filter(F.action == SubmissionAction.CANCEL))
@flags.callback_answer(text="Preview cancelled.")
async def handle_cancel_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    preview_registry: PreviewDebugRegistry,
    telegram_logger: TelegramLogger,
) -> None:
    if not (submission := await validate_submission(callback, callback_data, state)):
        return

    preview_entry = preview_registry.get(submission.submission_id)
    repository = preview_entry.repository if preview_entry else None

    if repository and callback.from_user:
        await telegram_logger.log_post_cancelled(callback.from_user, repository)

    await _finalize_submission(bot, state, preview_registry, submission, callback)


async def _finalize_submission(
    bot: Bot,
    state: FSMContext,
    preview_registry: PreviewDebugRegistry,
    submission: SubmissionData,
    callback: CallbackQuery,
) -> None:
    targets = list(submission.cleanup_targets)
    if callback and callback.message:
        targets.append((callback.message.chat.id, callback.message.message_id))
    await cleanup_messages(bot, targets)

    preview_registry.discard(submission.submission_id)
    await state.clear()
