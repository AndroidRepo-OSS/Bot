# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from typing import TYPE_CHECKING
from uuid import uuid4

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

from bot.integrations.ai import NonAndroidProjectError
from bot.modules.post.utils.messages import render_post_caption
from bot.modules.post.utils.models import PostStates
from bot.modules.post.utils.preview import build_debug_link, build_preview_keyboard, render_banner
from bot.modules.post.utils.repositories import parse_repository_url, select_fetcher
from bot.modules.post.utils.session import cleanup_messages, reset_submission_state, safe_delete, update_progress

if TYPE_CHECKING:
    from aiogram.filters import CommandObject
    from aiogram.fsm.context import FSMContext
    from aiogram.types import Message

    from bot.integrations.ai import SummaryAgent
    from bot.integrations.ai.models import RepositorySummary, SummaryResult
    from bot.integrations.repositories import GitHubRepositoryFetcher, GitLabRepositoryFetcher, RepositoryInfo
    from bot.modules.post.utils.repositories import RepositoryLocator
    from bot.services import PreviewDebugRegistry, TelegramLogger


router = Router(name="post-command")


@router.message(Command("post"))
async def handle_post_command(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    preview_registry: PreviewDebugRegistry,
    summary_agent: SummaryAgent,
    github_fetcher: GitHubRepositoryFetcher,
    gitlab_fetcher: GitLabRepositoryFetcher,
    telegram_logger: TelegramLogger,
) -> None:
    await reset_submission_state(state, preview_registry)
    await state.update_data(command_chat_id=message.chat.id, command_message_id=message.message_id)

    if args := (command.args or "").strip():
        await process_repository_request(
            message,
            args,
            state,
            preview_registry=preview_registry,
            summary_agent=summary_agent,
            github_fetcher=github_fetcher,
            gitlab_fetcher=gitlab_fetcher,
            telegram_logger=telegram_logger,
        )
        return

    await state.set_state(PostStates.waiting_for_url)
    prompt = await message.answer("Send the GitHub or GitLab repository URL you want to share.")
    await state.update_data(prompt_chat_id=prompt.chat.id, prompt_message_id=prompt.message_id)


@router.message(PostStates.waiting_for_url)
async def handle_repository_input(
    message: Message,
    state: FSMContext,
    preview_registry: PreviewDebugRegistry,
    summary_agent: SummaryAgent,
    github_fetcher: GitHubRepositoryFetcher,
    gitlab_fetcher: GitLabRepositoryFetcher,
    telegram_logger: TelegramLogger,
) -> None:
    if not message.text:
        await message.answer("Please send the repository URL as plain text.")
        return

    await process_repository_request(
        message,
        message.text,
        state,
        preview_registry=preview_registry,
        summary_agent=summary_agent,
        github_fetcher=github_fetcher,
        gitlab_fetcher=gitlab_fetcher,
        telegram_logger=telegram_logger,
    )


async def process_repository_request(
    message: Message,
    raw_url: str,
    state: FSMContext,
    *,
    preview_registry: PreviewDebugRegistry,
    summary_agent: SummaryAgent,
    github_fetcher: GitHubRepositoryFetcher,
    gitlab_fetcher: GitLabRepositoryFetcher,
    telegram_logger: TelegramLogger,
) -> None:
    locator = parse_repository_url(raw_url)
    progress = await message.answer("[1/3] Fetching repository...")

    repository = await _fetch_repository(locator, github_fetcher=github_fetcher, gitlab_fetcher=gitlab_fetcher)

    if message.from_user:
        await telegram_logger.log_post_started(message.from_user, repository)

    await update_progress(progress, "[2/3] Generating AI summary...")

    summary_result = await _summarize_repository(message, state, telegram_logger, repository, progress, summary_agent)
    if not summary_result:
        return

    await update_progress(progress, "[3/3] Rendering preview...")
    await _render_and_store_preview(message, state, repository, summary_result, preview_registry=preview_registry)

    await safe_delete(message.bot, progress.chat.id, progress.message_id)


async def _cleanup_rejected_submission(message: Message, error_message: Message, state: FSMContext) -> None:
    state_data = await state.get_data()
    targets = [
        (message.chat.id, message.message_id),
        (error_message.chat.id, error_message.message_id),
        (state_data.get("prompt_chat_id"), state_data.get("prompt_message_id")),
        (state_data.get("command_chat_id"), state_data.get("command_message_id")),
    ]

    await cleanup_messages(message.bot, targets, delay=10)
    await state.clear()


async def _fetch_repository(
    locator: RepositoryLocator, *, github_fetcher: GitHubRepositoryFetcher, gitlab_fetcher: GitLabRepositoryFetcher
) -> RepositoryInfo:
    fetcher = select_fetcher(locator, github_fetcher=github_fetcher, gitlab_fetcher=gitlab_fetcher)
    return await fetcher.fetch_repository(locator.owner, locator.name)


async def _reject_non_android(
    message: Message,
    state: FSMContext,
    telegram_logger: TelegramLogger,
    repository: RepositoryInfo,
    exc: NonAndroidProjectError,
    progress: Message,
) -> None:
    await safe_delete(message.bot, progress.chat.id, progress.message_id)
    error_msg = await message.answer(
        "❌ <b>This repository doesn't appear to be Android-related.</b>\n\n"
        f"<i>{exc.reason}</i>\n\n"
        "Only Android apps, tools, and related projects can be shared."
    )

    if message.from_user:
        await telegram_logger.log_post_rejected(message.from_user, repository, exc.reason)

    await _cleanup_rejected_submission(message, error_msg, state)


async def _summarize_repository(
    message: Message,
    state: FSMContext,
    telegram_logger: TelegramLogger,
    repository: RepositoryInfo,
    progress: Message,
    summary_agent: SummaryAgent,
) -> SummaryResult | None:
    try:
        return await summary_agent.summarize(repository)
    except NonAndroidProjectError as exc:
        await _reject_non_android(message, state, telegram_logger, repository, exc, progress)
        return None


async def _render_preview(
    message: Message,
    repository: RepositoryInfo,
    summary_result: SummaryResult,
    *,
    preview_registry: PreviewDebugRegistry,
) -> tuple[str, str, bytes, Message, str | None]:
    banner_bytes = await render_banner(repository, summary_result.summary)
    caption = render_post_caption(repository, summary_result.summary)

    submission_id = uuid4().hex
    preview_registry.save(submission_id, repository, summary_model=summary_result.model_name)

    debug_url = await build_debug_link(message.bot, f"preview-{submission_id}")
    keyboard = build_preview_keyboard(submission_id, debug_url)

    preview = await message.answer_photo(
        photo=BufferedInputFile(banner_bytes, filename=f"{repository.name}.png"),
        caption=caption,
        reply_markup=keyboard.as_markup(),
    )

    return submission_id, caption, banner_bytes, preview, debug_url


async def _render_and_store_preview(
    message: Message,
    state: FSMContext,
    repository: RepositoryInfo,
    summary_result: SummaryResult,
    *,
    preview_registry: PreviewDebugRegistry,
) -> None:
    submission_id, caption, banner_bytes, preview, debug_url = await _render_preview(
        message, repository, summary_result, preview_registry=preview_registry
    )

    await _store_submission_state(
        state,
        submission_id,
        caption=caption,
        banner_bytes=banner_bytes,
        preview=preview,
        message=message,
        summary=summary_result.summary,
        debug_url=debug_url,
        summary_model=summary_result.model_name,
    )


async def _store_submission_state(
    state: FSMContext,
    submission_id: str,
    *,
    caption: str,
    banner_bytes: bytes,
    preview: Message,
    message: Message,
    summary: RepositorySummary,
    debug_url: str | None,
    summary_model: str,
) -> None:
    await state.set_state(PostStates.waiting_for_confirmation)
    await state.update_data(
        submission_id=submission_id,
        caption=caption,
        banner_b64=base64.b64encode(banner_bytes).decode("ascii"),
        preview_chat_id=preview.chat.id,
        preview_message_id=preview.message_id,
        original_chat_id=message.chat.id,
        original_message_id=message.message_id,
        summary=summary.model_dump(mode="json"),
        debug_url=debug_url,
        summary_model=summary_model,
    )
