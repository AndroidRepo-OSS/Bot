# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from anyio import create_task_group

from bot.integrations.ai import NonAndroidProjectError, RepositorySummaryError
from bot.integrations.repositories.errors import RepositoryClientError
from bot.logging import get_logger
from bot.modules.post.utils.links import build_channel_message_link
from bot.modules.post.utils.messages import render_post_caption
from bot.modules.post.utils.models import PostStates, SubmissionData
from bot.modules.post.utils.preview import build_debug_link, build_preview_keyboard, render_banner
from bot.modules.post.utils.repositories import RepositoryUrlParseError, parse_repository_url, select_fetcher
from bot.modules.post.utils.session import cleanup_messages, reset_submission_state, safe_delete, update_progress

if TYPE_CHECKING:
    from aiogram.filters import CommandObject
    from aiogram.fsm.context import FSMContext
    from aiogram.types import Message

    from bot.config import BotSettings
    from bot.db import PostsRepository
    from bot.db.models.post import Post
    from bot.integrations.ai import SummaryAgent, SummaryResult
    from bot.integrations.nasa import NasaApodService
    from bot.integrations.repositories import GitHubRepositoryFetcher, GitLabRepositoryFetcher, RepositoryInfo
    from bot.services import PreviewDebugRegistry, TelegramLogger


router = Router(name="post-command")
logger = get_logger(__name__)


@router.message(Command("post"))
@router.message(PostStates.waiting_for_url)
async def handle_post(
    message: Message,
    state: FSMContext,
    preview_registry: PreviewDebugRegistry,
    summary_agent: SummaryAgent,
    github_fetcher: GitHubRepositoryFetcher,
    gitlab_fetcher: GitLabRepositoryFetcher,
    telegram_logger: TelegramLogger,
    posts_repository: PostsRepository,
    settings: BotSettings,
    nasa_apod_service: NasaApodService,
    command: CommandObject | None = None,
) -> None:
    raw_url = await _extract_raw_url(command, message, state, preview_registry)
    if raw_url is None:
        return

    try:
        locator = parse_repository_url(raw_url)
    except RepositoryUrlParseError as exc:
        await logger.awarning("Invalid repository URL", error=str(exc))
        await _reject_submission(message, state, f"❌ Invalid repository URL: {exc.reason}")
        return

    progress = await message.answer("[1/3] Fetching repository...")

    try:
        try:
            fetcher = select_fetcher(locator, github_fetcher=github_fetcher, gitlab_fetcher=gitlab_fetcher)
            repository = await fetcher.fetch_repository(locator.owner, locator.name)
        except RepositoryClientError as exc:
            await logger.awarning(
                "Repository client error", platform=exc.platform, status=exc.status, details=exc.details
            )
            await _reject_submission(message, state, f"❌ Failed to fetch repository: {exc}")
            return

        if message.from_user:
            await telegram_logger.log_post_started(message.from_user, repository)

        recent_post: Post | None = None
        already_posted = False

        async def load_recent_post() -> None:
            nonlocal recent_post
            recent_post = await posts_repository.get_recent_post(
                platform=locator.platform, owner=locator.owner, name=locator.name, months=3
            )

        async def load_already_posted() -> None:
            nonlocal already_posted
            already_posted = await posts_repository.is_posted(
                platform=locator.platform, owner=locator.owner, name=locator.name
            )

        async with create_task_group() as tg:
            tg.start_soon(load_recent_post)
            tg.start_soon(load_already_posted)

        if recent_post:
            next_allowed = recent_post.posted_at + timedelta(days=90)
            link = build_channel_message_link(settings.post_channel_id, recent_post.channel_message_id)
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="See previous post", url=link)]]
            )
            await telegram_logger.log_post_recently_posted(
                message.from_user,
                repository,
                last_posted_at=recent_post.posted_at,
                next_allowed_at=next_allowed,
                channel_message_id=recent_post.channel_message_id,
                channel_link=link,
            )
            await _reject_submission(
                message,
                state,
                "❌ This repository was already posted in the last 3 months. Please wait before reposting.",
                reply_markup=keyboard,
            )
            return

        if already_posted:
            await message.answer("ℹ️ This repository was already posted. Publishing will refresh its record.")

        await update_progress(progress, "[2/3] Generating AI summary...")

        try:
            summary_result = await _summarize_repository(
                message, state, telegram_logger, repository, progress, summary_agent
            )
        except RepositorySummaryError as exc:
            await logger.awarning("Summary generation failed", original_error=str(exc.original_error))
            await _reject_submission(message, state, "Could not generate summary. Please try again later.")
            return
        if not summary_result:
            return

        await update_progress(progress, "[3/3] Rendering preview...")

        try:
            submission_id, caption, banner_bytes, preview, debug_url = await _render_preview(
                message,
                repository,
                summary_result,
                preview_registry=preview_registry,
                nasa_apod_service=nasa_apod_service,
            )
        except (OSError, TelegramAPIError) as exc:
            await _reject_submission(message, state, f"❌ Failed rendering preview: {exc}")
            return

        await state.set_state(PostStates.waiting_for_confirmation)
        await state.update_data(
            submission_id=submission_id,
            caption=caption,
            banner_b64=base64.b64encode(banner_bytes).decode("ascii"),
            preview_chat_id=preview.chat.id,
            preview_message_id=preview.message_id,
            original_chat_id=message.chat.id,
            original_message_id=message.message_id,
            summary=summary_result.summary.model_dump(mode="json"),
            debug_url=debug_url,
            summary_model=summary_result.model_name,
            repository_platform=locator.platform,
            repository_owner=locator.owner,
            repository_name=locator.name,
        )
    finally:
        await safe_delete(message.bot, progress.chat.id, progress.message_id)


async def _cleanup_rejected_submission(message: Message, error_message: Message, state: FSMContext) -> None:
    state_data = await state.get_data()
    submission = SubmissionData.from_state(state_data)

    def _fallback_targets(data: dict[str, object]) -> list[tuple[int, int]]:
        keys = (("command_chat_id", "command_message_id"), ("prompt_chat_id", "prompt_message_id"))
        targets: list[tuple[int, int]] = []

        for chat_key, message_key in keys:
            chat_id = data.get(chat_key)
            message_id = data.get(message_key)

            if isinstance(chat_id, int) and isinstance(message_id, int):
                targets.append((chat_id, message_id))

        return targets

    extra_targets = submission.cleanup_targets if submission else _fallback_targets(state_data)
    targets = [(message.chat.id, message.message_id), (error_message.chat.id, error_message.message_id), *extra_targets]

    await cleanup_messages(message.bot, targets, delay=10)
    await state.clear()


async def _reject_submission(
    message: Message, state: FSMContext, text: str, *, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    error_message = await message.answer(text, reply_markup=reply_markup)
    await _cleanup_rejected_submission(message, error_message, state)


async def _extract_raw_url(
    command: CommandObject | None, message: Message, state: FSMContext, preview_registry: PreviewDebugRegistry
) -> str | None:
    if command is None:
        if not message.text:
            await message.answer("Please send the repository URL as plain text.")
            return None
        return message.text

    await reset_submission_state(state, preview_registry)
    await state.update_data(command_chat_id=message.chat.id, command_message_id=message.message_id)

    if args := (command.args or "").strip():
        return args

    await state.set_state(PostStates.waiting_for_url)
    prompt = await message.answer("Send the GitHub or GitLab repository URL you want to share.")
    await state.update_data(prompt_chat_id=prompt.chat.id, prompt_message_id=prompt.message_id)
    return None


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
        await safe_delete(message.bot, progress.chat.id, progress.message_id)
        error_msg = await message.answer(
            "❌ <b>This repository doesn't appear to be Android-related.</b>\n\n"
            f"<i>{exc.reason}</i>\n\n"
            "Only Android apps, tools, and related projects can be shared."
        )

        if message.from_user:
            await telegram_logger.log_post_rejected(message.from_user, repository, exc.reason)

        await _cleanup_rejected_submission(message, error_msg, state)


async def _render_preview(
    message: Message,
    repository: RepositoryInfo,
    summary_result: SummaryResult,
    *,
    preview_registry: PreviewDebugRegistry,
    nasa_apod_service: NasaApodService,
) -> tuple[str, str, bytes, Message, str | None]:
    banner_bytes: bytes | None = None

    async def render_banner_task() -> None:
        nonlocal banner_bytes
        banner_bytes = await render_banner(repository, summary_result.summary, nasa_apod_service)

    async with create_task_group() as tg:
        tg.start_soon(render_banner_task)
        caption = render_post_caption(repository, summary_result.summary)

    assert banner_bytes is not None

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
