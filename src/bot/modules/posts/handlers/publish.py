# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from datetime import UTC, datetime
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InaccessibleMessage

from bot.config import Settings, settings
from bot.database import has_pending_scheduled_post, schedule_post, submit_app
from bot.modules.posts.callbacks import PostAction, PostCallback
from bot.modules.posts.utils import get_project_name, try_edit_message
from bot.scheduler import PostScheduler
from bot.utils.models import EnhancedRepositoryData

router = Router(name="publish_post")


async def _safe_edit_message(callback: CallbackQuery, text: str) -> None:
    if callback.message and not isinstance(callback.message, InaccessibleMessage):
        await try_edit_message(callback.message, text)


async def _validate_callback_data(
    callback: CallbackQuery, state: FSMContext
) -> tuple[str, EnhancedRepositoryData, Any] | None:
    if (
        isinstance(callback.message, InaccessibleMessage)
        or not callback.bot
        or not callback.message
    ):
        return None

    data = await state.get_data()
    post_text, enhanced_data, banner_buffer = (
        data.get("post_text"),
        data.get("enhanced_data"),
        data.get("banner_buffer"),
    )

    if not post_text or not enhanced_data:
        return None

    if not banner_buffer:
        error_text = (
            "❌ <b>Banner Required</b>\n\n"
            "Cannot publish without a banner.\n\n"
            "💡 Try regenerating the post to create a new banner."
        )
        await try_edit_message(callback.message, error_text)
        return None

    return post_text, enhanced_data, banner_buffer


async def _validate_settings_and_banner(
    callback: CallbackQuery, banner_buffer: Any, enhanced_data: EnhancedRepositoryData
) -> Settings | None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return None

    if not settings.channel_id:
        error_text = (
            "❌ <b>Configuration Error</b>\n\n"
            "Channel ID is not configured.\n\n"
            "Please contact the administrator."
        )
        await try_edit_message(callback.message, error_text)
        return None

    banner_size = len(banner_buffer.getvalue())
    if banner_size > 10 * 1024 * 1024:
        get_project_name(enhanced_data.repository, enhanced_data.ai_content)
        error_text = (
            "❌ <b>Banner Too Large</b>\n\n"
            f"Banner size: {banner_size / 1024 / 1024:.1f}MB\n"
            "Maximum allowed: 10MB\n\n"
            "💡 Try regenerating with a smaller banner."
        )
        await _safe_edit_message(callback, error_text)
        return None

    return settings


async def _publish_immediately(
    callback: CallbackQuery,
    settings: Settings,
    post_text: str,
    banner_buffer: Any,
    banner_filename: str,
    repository: Any,
) -> str | None:
    if not callback.bot:
        return None

    try:
        await callback.bot.get_chat(settings.channel_id)
    except Exception as perm_error:
        error_text = (
            "❌ <b>Permission Error</b>\n\n"
            "Bot cannot access the channel.\n\n"
            f"<b>Error:</b> {perm_error!s}\n\n"
            "Please check bot permissions."
        )
        await _safe_edit_message(callback, error_text)
        return None

    banner_input = BufferedInputFile(
        banner_buffer.getvalue(),
        filename=banner_filename,
    )

    sent_message = await callback.bot.send_photo(
        chat_id=settings.channel_id, photo=banner_input, caption=post_text
    )

    await submit_app(repository, sent_message.message_id)

    return "✅ <b>Post Published!</b>\n\n<i>Post sent to channel and saved to database.</i>"


async def _schedule_post(
    callback: CallbackQuery,
    scheduler: PostScheduler,
    repository: Any,
    post_text: str,
    banner_buffer: Any,
    banner_filename: str,
    next_slot: datetime,
) -> str | None:
    has_pending = await has_pending_scheduled_post(repository.id)

    if has_pending:
        error_text = (
            "⚠️ <b>Post Already Scheduled</b>\n\n"
            "This repository already has a post scheduled for publication.\n\n"
            "<i>To avoid spam, only one post per repository can be "
            "scheduled at a time.</i>"
        )
        await _safe_edit_message(callback, error_text)
        return None

    job_id = f"post_{repository.id}_{int(next_slot.timestamp())}"

    scheduled_post = await schedule_post(
        repository=repository,
        post_text=post_text,
        banner_buffer=banner_buffer,
        banner_filename=banner_filename,
        scheduled_time=next_slot,
        job_id=job_id,
    )

    await scheduler.schedule_post(scheduled_post, post_text, banner_buffer, banner_filename)

    return (
        "⏰ <b>Post Scheduled Successfully!</b>\n\n"
        f"<b>Scheduled for:</b> {next_slot.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "<i>Post will be automatically published at the scheduled time.</i>"
    )


async def _process_post_publication(
    callback: CallbackQuery,
    enhanced_data: EnhancedRepositoryData,
    post_text: str,
    banner_buffer: Any,
    settings: Settings,
) -> None:
    if not callback.bot:
        await _safe_edit_message(callback, "❌ Bot instance not available")
        return

    repository = enhanced_data.repository
    project_name = get_project_name(repository, enhanced_data.ai_content)

    scheduler = PostScheduler(callback.bot, settings)
    current_time = datetime.now(UTC)
    next_slot = await scheduler.get_next_available_slot(current_time)

    banner_filename = f"{project_name.lower().replace(' ', '_')}_banner.png"

    time_diff = (next_slot - current_time).total_seconds()
    can_post_immediately = time_diff <= 60

    if can_post_immediately:
        success_text = await _publish_immediately(
            callback, settings, post_text, banner_buffer, banner_filename, repository
        )
        if success_text:
            await _safe_edit_message(callback, success_text)
    else:
        success_text = await _schedule_post(
            callback,
            scheduler,
            repository,
            post_text,
            banner_buffer,
            banner_filename,
            next_slot,
        )
        if success_text:
            await _safe_edit_message(callback, success_text)


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH))
async def publish_post_handler(callback: CallbackQuery, state: FSMContext) -> None:
    validation_result = await _validate_callback_data(callback, state)
    if not validation_result:
        return

    post_text, enhanced_data, banner_buffer = validation_result

    settings = await _validate_settings_and_banner(callback, banner_buffer, enhanced_data)
    if not settings:
        return

    try:
        await _process_post_publication(
            callback, enhanced_data, post_text, banner_buffer, settings
        )

    except Exception as e:
        error_text = (
            "❌ <b>Publishing Failed</b>\n\n"
            f"<b>Error:</b> {e!s}\n\n"
            "<i>Check channel ID and bot permissions.</i>"
        )
        await _safe_edit_message(callback, error_text)

    finally:
        if banner_buffer:
            banner_buffer.close()

    await state.clear()
