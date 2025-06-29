# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import asyncio
import contextlib
from datetime import UTC, datetime
from io import BytesIO

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings, settings
from bot.database import can_submit_app, has_pending_scheduled_post, schedule_post, submit_app
from bot.database.operations import get_scheduled_posts_after_time
from bot.scheduler import PostScheduler
from bot.utils.banner_generator import generate_banner
from bot.utils.enums import KeyboardType, PostAction, PostCallback
from bot.utils.models import EnhancedRepositoryData, GitHubRepository, GitLabRepository
from bot.utils.repository_client import RepositoryClient
from bot.utils.states import PostStates

router = Router(name="posts")


def get_project_name(enhanced_data: EnhancedRepositoryData) -> str:
    if enhanced_data.ai_content and enhanced_data.ai_content.project_name:
        return enhanced_data.ai_content.project_name
    return enhanced_data.repository.name


def get_description(enhanced_data: EnhancedRepositoryData) -> str | None:
    if enhanced_data.ai_content:
        return enhanced_data.ai_content.enhanced_description
    return enhanced_data.repository.description


def get_tags(enhanced_data: EnhancedRepositoryData) -> list[str]:
    if enhanced_data.ai_content and enhanced_data.ai_content.relevant_tags:
        return enhanced_data.ai_content.relevant_tags
    return enhanced_data.repository.topics or []


def format_post(enhanced_data: EnhancedRepositoryData) -> str:
    project_name = get_project_name(enhanced_data)
    description = get_description(enhanced_data)
    tags = get_tags(enhanced_data)

    sections = [f"<b>{project_name}</b>"]

    if description:
        sections.append(f"<i>{description}</i>")

    if enhanced_data.ai_content and enhanced_data.ai_content.key_features:
        features_text = "\n".join(
            f"• {feature}" for feature in enhanced_data.ai_content.key_features
        )
        sections.append(f"✨ <b>Key Features:</b>\n{features_text}")

    platform_name = (
        "GitHub" if isinstance(enhanced_data.repository, GitHubRepository) else "GitLab"
    )
    links = [f'• <a href="{enhanced_data.repository.url}">{platform_name} Repository</a>']

    if enhanced_data.ai_content and enhanced_data.ai_content.important_links:
        additional_links = [
            f'• <a href="{link.url}">{link.title}</a>'
            for link in enhanced_data.ai_content.important_links
        ]
        links.extend(additional_links)

    sections.append("🔗 <b>Links:</b>\n" + "\n".join(links))

    if tags:
        hashtags = " ".join(f"#{tag}" for tag in tags)
        sections.append(f"🏷️ <b>Tags:</b> {hashtags}")

    return "\n\n".join(sections)


async def safe_edit_message(
    target: Message | CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    message = target.message if isinstance(target, CallbackQuery) else target
    if not message or isinstance(message, InaccessibleMessage):
        return

    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=markup)
        else:
            await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        with contextlib.suppress(TelegramBadRequest):
            await message.answer(text, reply_markup=markup)


def create_keyboard(keyboard_type: KeyboardType) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if keyboard_type == KeyboardType.CONFIRMATION:
        builder.button(text="✅ Confirm", callback_data=PostCallback(action=PostAction.CONFIRM))
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2)
    elif keyboard_type == KeyboardType.PREVIEW:
        builder.button(text="✅ Publish", callback_data=PostCallback(action=PostAction.PUBLISH))
        builder.button(
            text="🔄 Regenerate", callback_data=PostCallback(action=PostAction.REGENERATE)
        )
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2, 1)

    return builder.as_markup()


async def get_session_data(
    callback: CallbackQuery, state: FSMContext
) -> tuple[str, EnhancedRepositoryData, BytesIO] | None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return None

    data = await state.get_data()
    post_text = data.get("post_text")
    enhanced_data = data.get("enhanced_data")
    banner_buffer = data.get("banner_buffer")

    if (
        not isinstance(post_text, str)
        or not enhanced_data
        or not isinstance(banner_buffer, BytesIO)
    ):
        await safe_edit_message(
            callback.message,
            "❌ <b>Error</b>\n\nSession expired or missing data. Try /post again.",
        )
        return None

    if not settings.channel_id:
        await safe_edit_message(callback.message, "❌ <b>Error</b>\n\nChannel ID not configured.")
        return None

    banner_size = len(banner_buffer.getvalue())
    if banner_size > 10 * 1024 * 1024:
        await safe_edit_message(callback.message, "❌ <b>Error</b>\n\nBanner too large (>10MB).")
        return None

    return post_text, enhanced_data, banner_buffer


async def try_publish_post(
    callback: CallbackQuery,
    settings: Settings,
    post_text: str,
    banner_buffer: BytesIO,
    banner_filename: str,
    repository: GitHubRepository | GitLabRepository,
) -> str | None:
    if not callback.bot:
        return None

    try:
        await callback.bot.get_chat(settings.channel_id)
    except Exception as e:
        error_text = (
            "❌ <b>Permission Error</b>\n\n"
            "Bot cannot access the channel.\n\n"
            f"<b>Error:</b> {e!s}\n\n"
            "Please check bot permissions."
        )
        await safe_edit_message(callback, error_text)
        return None

    banner_input = BufferedInputFile(banner_buffer.getvalue(), filename=banner_filename)
    sent_message = await callback.bot.send_photo(
        chat_id=settings.channel_id, photo=banner_input, caption=post_text
    )
    await submit_app(repository, sent_message.message_id)

    return "✅ <b>Post Published!</b>\n\n<i>Post sent to channel and saved to database.</i>"


async def try_schedule_post(
    scheduler: PostScheduler,
    repository: GitHubRepository | GitLabRepository,
    post_text: str,
    banner_buffer: BytesIO,
    banner_filename: str,
) -> str | None:
    if await has_pending_scheduled_post(repository.id):
        return None

    next_slot = await scheduler.get_next_available_slot()
    job_id = f"post_{repository.id}_{int(next_slot.timestamp())}"

    scheduled_post = await schedule_post(
        repository=repository,
        post_text=post_text,
        banner_buffer=banner_buffer,
        banner_filename=banner_filename,
        scheduled_time=next_slot,
        job_id=job_id,
    )

    await scheduler.schedule_post(
        post=scheduled_post,
        post_text=post_text,
        banner_buffer=banner_buffer,
        banner_filename=banner_filename,
    )

    return (
        "⏰ <b>Post Scheduled Successfully!</b>\n\n"
        f"<b>Scheduled for:</b> {next_slot.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "<i>Post will be automatically published at the scheduled time.</i>"
    )


async def process_post_publication(
    callback: CallbackQuery,
    enhanced_data: EnhancedRepositoryData,
    post_text: str,
    banner_buffer: BytesIO,
    settings: Settings,
) -> None:
    if not callback.bot:
        await safe_edit_message(callback, "❌ Bot instance not available")
        return

    repository = enhanced_data.repository
    project_name = get_project_name(enhanced_data)
    banner_filename = f"{project_name.lower().replace(' ', '_')}_banner.png"

    scheduler = PostScheduler(callback.bot, settings)
    current_time = datetime.now(UTC)
    next_slot = await scheduler.get_next_available_slot(current_time)
    time_diff = (next_slot - current_time).total_seconds()

    if time_diff <= 60:
        success_text = await try_publish_post(
            callback, settings, post_text, banner_buffer, banner_filename, repository
        )
        if success_text:
            await safe_edit_message(callback, success_text)
    else:
        success_text = await try_schedule_post(
            scheduler, repository, post_text, banner_buffer, banner_filename
        )
        if success_text:
            await safe_edit_message(callback, success_text)
        else:
            await safe_edit_message(
                callback,
                "⚠️ <b>Post Already Scheduled</b>\n\n"
                "This repository already has a post scheduled for publication.\n\n"
                "<i>To avoid spam, only one post per repository can be scheduled.</i>",
            )


async def process_post_content(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData
) -> None:
    project_name = get_project_name(enhanced_data)
    await safe_edit_message(
        message,
        "🎨 <b>Finalizing Content</b>\n\n<i>Formatting post and generating banner...</i>",
    )

    try:
        post_text_task = asyncio.create_task(asyncio.to_thread(format_post, enhanced_data))
        banner_task = asyncio.create_task(asyncio.to_thread(generate_banner, project_name))

        post_text, banner_result = await asyncio.gather(
            post_text_task, banner_task, return_exceptions=True
        )

        if isinstance(post_text, Exception):
            raise post_text

        banner_buffer = None if isinstance(banner_result, Exception) else banner_result

    except Exception:
        await safe_edit_message(
            message, "❌ <b>Error</b>\n\nContent generation failed. Try /post again."
        )
        await state.clear()
        return

    await state.update_data(
        enhanced_data=enhanced_data,
        post_text=str(post_text),
        banner_buffer=banner_buffer,
    )
    await state.set_state(PostStates.previewing_post)

    if banner_buffer and isinstance(banner_buffer, BytesIO):
        await send_successful_preview(message, banner_buffer, str(post_text))
    else:
        await safe_edit_message(message, "❌ <b>Banner Generation Failed</b>\n\nTry /post again.")
        await state.clear()


async def send_successful_preview(
    message: Message, banner_buffer: BytesIO, post_text: str
) -> None:
    preview_header = "✅ <b>Post Ready</b>\n\n<i>Review and publish when ready</i>"
    banner_input = BufferedInputFile(banner_buffer.getvalue(), filename="banner.png")

    if message.photo:
        await message.delete()
        await message.answer(preview_header)
        await message.answer_photo(
            photo=banner_input,
            caption=post_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )
    else:
        await safe_edit_message(message, preview_header)
        await message.answer_photo(
            photo=banner_input,
            caption=post_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )


async def show_error(message: Message, state: FSMContext, error_text: str) -> None:
    await safe_edit_message(message, f"❌ <b>Error</b>\n\n{error_text}")
    await state.clear()


@router.message(Command("scheduled"))
async def list_scheduled_posts(message: Message) -> None:
    now = datetime.now(UTC)

    scheduled_posts = await get_scheduled_posts_after_time(now, now.replace(year=now.year + 1))

    if not scheduled_posts:
        await message.answer(
            "📅 <b>No Scheduled Posts</b>\n\nThere are no posts currently scheduled."
        )
        return

    unique_posts = {}
    for post in scheduled_posts:
        key = f"{post.id}_{post.repository_id}_{post.scheduled_time}"
        if key not in unique_posts:
            unique_posts[key] = post

    final_posts = list(unique_posts.values())

    text = "📅 <b>Scheduled Posts</b>\n\n"

    for i, post in enumerate(final_posts):
        status = "⏰ Pending" if not post.is_published else "✅ Published"
        text += (
            f"<b>ID:</b> {post.id}\n"
            f"<b>Repository:</b> {post.repository_full_name}\n"
            f"<b>Scheduled:</b> {post.scheduled_time.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"<b>Status:</b> {status}"
        )

        if i < len(final_posts) - 1:
            text += "\n" + "─" * 30 + "\n"

    await message.answer(text)


@router.message(Command("post"))
async def post_command_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    banner_buffer = data.get("banner_buffer")
    if banner_buffer:
        banner_buffer.close()

    await state.clear()
    await state.set_state(PostStates.waiting_for_repository_url)

    await message.reply(
        "📱 <b>Create Repository Post</b>\n\n"
        "Send a GitHub or GitLab repository URL to generate a post.\n\n"
        "💡 Use /cancel to abort anytime."
    )


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "cancel")
async def cancel_command_handler(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        await message.reply(
            "❌ <b>No Active Session</b>\n\n"
            "You don't have any post creation in progress.\n\n"
            "💡 Use /post to start creating a new post."
        )
        return

    if banner_buffer := (await state.get_data()).get("banner_buffer"):
        banner_buffer.close()

    await state.clear()
    await message.reply(
        "❌ <b>Session Cancelled</b>\n\n"
        "Your post creation has been cancelled.\n\n"
        "💡 Use /post to start over."
    )


@router.message(PostStates.waiting_for_repository_url, F.text)
async def repository_url_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply(
            "❌ <b>Invalid Input</b>\n\n"
            "Please provide a valid repository URL from GitHub or GitLab."
        )
        return

    url = message.text.strip()

    async with RepositoryClient() as client:
        if not client.is_valid_repository_url(url):
            await message.reply(
                "❌ <b>Invalid Repository URL</b>\n\n"
                "Please provide a valid repository URL from GitHub or GitLab.\n\n"
                "💡 Use /cancel to abort."
            )
            return

    await state.update_data(repository_url=url)
    await state.set_state(PostStates.waiting_for_confirmation)

    await message.reply(
        f"✅ <b>Repository Detected</b>\n\n"
        f"<b>URL:</b> <code>{url}</code>\n\n"
        f"Ready to create the post?",
        reply_markup=create_keyboard(KeyboardType.CONFIRMATION),
    )


@router.message(PostStates.waiting_for_repository_url)
async def invalid_repository_url_handler(message: Message) -> None:
    await message.reply(
        "❌ <b>Invalid Input</b>\n\n"
        "Please send a valid GitHub or GitLab repository URL.\n\n"
        "💡 Use /cancel to abort."
    )


@router.callback_query(PostCallback.filter(F.action == PostAction.CONFIRM))
async def confirm_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    data = await state.get_data()
    repository_url = data.get("repository_url")
    if not repository_url:
        return

    await safe_edit_message(
        callback.message,
        "🔄 <b>Validating Repository</b>\n\n<i>Checking posting eligibility...</i>",
    )

    try:
        async with RepositoryClient() as client:
            if not client.is_valid_repository_url(repository_url):
                await safe_edit_message(
                    callback.message,
                    f"❌ <b>Invalid Repository</b>\n\n"
                    f"<b>URL:</b> <code>{repository_url}</code>\n"
                    "Please check the URL and try again with /post",
                )
                await state.clear()
                return

            repository_data = await client.get_basic_repository_data(repository_url)
            can_submit, last_submission_date = await can_submit_app(repository_data.id)

            if not can_submit and last_submission_date:
                days_since = (datetime.now(tz=UTC) - last_submission_date.replace(tzinfo=UTC)).days
                remaining = 90 - days_since
                await show_error(
                    callback.message,
                    state,
                    f"Posted {days_since} days ago. Wait {remaining} more days to repost.",
                )
                return

            await safe_edit_message(
                callback.message,
                "🤖 <b>Generating AI Content</b>\n\n<i>Creating enhanced content...</i>",
            )

            enhanced_data = await client.get_enhanced_repository_data(
                repository_url,
                settings.openai_api_key.get_secret_value(),
                openai_base_url=settings.openai_base_url,
            )

            await process_post_content(callback.message, state, enhanced_data)

    except Exception as e:
        await show_error(callback.message, state, f"Processing failed: {e!s}")


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE))
async def regenerate_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    repository_url = (await state.get_data()).get("repository_url")

    if not repository_url:
        return

    regenerate_text = "🔄 <b>Regenerating Content</b>\n\n<i>Please wait...</i>"

    await safe_edit_message(callback.message, regenerate_text)

    await state.set_state(PostStates.waiting_for_confirmation)
    await confirm_post_handler(callback, state, PostCallback(action=PostAction.CONFIRM))


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH))
async def publish_post_handler(callback: CallbackQuery, state: FSMContext) -> None:
    session_data = await get_session_data(callback, state)
    if not session_data:
        return

    post_text, enhanced_data, banner_buffer = session_data

    try:
        await process_post_publication(callback, enhanced_data, post_text, banner_buffer, settings)

    except Exception as e:
        error_text = (
            "❌ <b>Publishing Failed</b>\n\n"
            f"<b>Error:</b> {e!s}\n\n"
            "<i>Check channel ID and bot permissions.</i>"
        )
        await safe_edit_message(callback, error_text)

    finally:
        banner_buffer.close()

    await state.clear()


@router.callback_query(PostCallback.filter(F.action == PostAction.CANCEL))
async def cancel_callback_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    if await state.get_state():
        if banner_buffer := (await state.get_data()).get("banner_buffer"):
            banner_buffer.close()
        await state.clear()

    cancel_text = "❌ <b>Post Creation Cancelled</b>\n\nYou can start again anytime with /post."

    await safe_edit_message(callback.message, cancel_text)
    await callback.answer("Post cancelled")
