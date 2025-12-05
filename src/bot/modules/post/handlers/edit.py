# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from aiogram import F, Router, flags
from aiogram.types import Message

from bot.modules.post.utils.messages import render_post_caption
from bot.modules.post.utils.models import PostStates, SubmissionAction, SubmissionCallback, SubmissionData
from bot.modules.post.utils.preview import render_banner, update_preview_message
from bot.modules.post.utils.session import safe_delete, update_progress, validate_submission

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery

    from bot.integrations.ai import RepositorySummary, RevisionAgent
    from bot.integrations.repositories import RepositoryInfo
    from bot.services import PreviewDebugRegistry, TelegramLogger


router = Router(name="post-edit")


@router.callback_query(SubmissionCallback.filter(F.action == SubmissionAction.EDIT))
@flags.callback_answer(text="Got it! Waiting for your edit request.")
async def handle_edit_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    preview_registry: PreviewDebugRegistry,
) -> None:
    submission = await validate_submission(callback, callback_data, state)
    if not submission:
        return

    if not preview_registry.get(submission.submission_id):
        await callback.answer("Repository context is missing. Please restart /post.", show_alert=True)
        await state.clear()
        return

    if not isinstance(callback.message, Message):
        await state.clear()
        return

    prompt = await callback.message.answer(
        "Send a message explaining how the preview should change. "
        "You can mention tone tweaks, features to highlight, or text to remove."
    )

    await _track_message(state, bot, prompt, "edit_prompt", submission)
    await state.set_state(PostStates.waiting_for_edit_instructions)


@router.message(PostStates.waiting_for_edit_instructions)
async def handle_edit_instructions(
    message: Message,
    state: FSMContext,
    preview_registry: PreviewDebugRegistry,
    revision_agent: RevisionAgent,
    bot: Bot,
    telegram_logger: TelegramLogger,
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please describe the desired edits using plain text.")
        return

    resolved = await _resolve_submission_context(state, preview_registry)
    if not resolved:
        await message.answer("This preview expired. Please run /post again.")
        await state.clear()
        return

    submission, repository, summary = resolved

    await _track_message(state, bot, message, "edit_request", submission)
    await safe_delete(bot, submission.edit_prompt_chat_id, submission.edit_prompt_message_id)

    progress = await message.answer("[1/3] Understanding your edit request...")
    await _track_message(state, bot, progress, "edit_status", submission)

    await _apply_revision(
        state, bot, progress, submission, repository, summary, text, revision_agent, preview_registry, telegram_logger
    )


async def _track_message(
    state: FSMContext, bot: Bot, message: Message, prefix: str, submission: SubmissionData
) -> None:
    if (old_chat := getattr(submission, f"{prefix}_chat_id", None)) and (
        old_msg := getattr(submission, f"{prefix}_message_id", None)
    ):
        await safe_delete(bot, old_chat, old_msg)

    await state.update_data({f"{prefix}_chat_id": message.chat.id, f"{prefix}_message_id": message.message_id})


async def _apply_revision(
    state: FSMContext,
    bot: Bot,
    progress: Message,
    submission: SubmissionData,
    repository: RepositoryInfo,
    summary: RepositorySummary,
    text: str,
    revision_agent: RevisionAgent,
    preview_registry: PreviewDebugRegistry,
    telegram_logger: TelegramLogger,
) -> None:
    revision_result = await revision_agent.revise(repository=repository, summary=summary, edit_request=text)
    updated_summary = revision_result.summary

    preview_registry.set_revision_model(submission.submission_id, revision_result.model_name)

    if progress.from_user and telegram_logger:
        await telegram_logger.log_post_edited(progress.from_user, repository, text)

    await update_progress(progress, "[2/3] Updating visuals...")
    banner_bytes = await render_banner(repository, updated_summary)
    caption = render_post_caption(repository, updated_summary)

    await update_progress(progress, "[3/3] Updating preview...")
    await update_preview_message(bot, submission, banner_bytes, caption)

    await state.update_data(
        caption=caption,
        banner_b64=base64.b64encode(banner_bytes).decode("ascii"),
        summary=updated_summary.model_dump(mode="json"),
        edit_prompt_chat_id=None,
        edit_prompt_message_id=None,
        summary_model=submission.summary_model,
        revision_model=revision_result.model_name,
    )
    await state.set_state(PostStates.waiting_for_confirmation)
    await update_progress(progress, "Preview updated! You can publish, edit again, or cancel.")


async def _resolve_submission_context(
    state: FSMContext, registry: PreviewDebugRegistry
) -> tuple[SubmissionData, RepositoryInfo, RepositorySummary] | None:
    submission = SubmissionData.from_state(await state.get_data())
    if not submission:
        return None

    entry = registry.get(submission.submission_id)
    summary = submission.repository_summary

    if not entry or not summary:
        return None

    return submission, entry.repository, summary
