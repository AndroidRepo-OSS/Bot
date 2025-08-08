# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import asyncio
from datetime import UTC, datetime
from io import BytesIO

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pydantic import Field

from bot.config import settings
from bot.database import can_submit, submit
from bot.filters.topic import SubmissionTopicFilter
from bot.utils.banner_generator import generate_banner
from bot.utils.enums import KeyboardType, PostAction
from bot.utils.logger import LogAction, get_logger
from bot.utils.models import EnhancedRepositoryData, GitHubRepository, GitLabRepository
from bot.utils.repo_client import RepositoryClient
from bot.utils.states import PostStates, clear_user_data, get_user_repository_url, update_user_data

router = Router(name="posts")
router.message.filter(
    F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]),
    SubmissionTopicFilter(),
    F.chat.id == settings.group_id,
)
router.callback_query.filter()


class PostCallback(CallbackData, prefix="post"):
    action: PostAction = Field(description="Action to perform on the post")


def get_project_name(enhanced_data: EnhancedRepositoryData) -> str:
    return (
        enhanced_data.ai_content.project_name
        if enhanced_data.ai_content
        else enhanced_data.repository.name
    )


async def edit_message_text_or_caption(message: Message, text: str) -> None:
    if message.photo:
        await message.edit_caption(caption=text)
        return
    await message.edit_text(text)


def format_post(enhanced_data: EnhancedRepositoryData) -> str:
    project_name = get_project_name(enhanced_data)
    ai = enhanced_data.ai_content
    repo = enhanced_data.repository

    description = ai.enhanced_description if ai and ai.enhanced_description else repo.description
    tags = ai.relevant_tags if ai and ai.relevant_tags else repo.topics

    sections = [f"<b>{project_name}</b>"]

    if description:
        sections.append(f"<i>{description}</i>")

    if ai and ai.key_features:
        features_text = "\n".join(f"• {feature}" for feature in ai.key_features)
        sections.append(f"✨ <b>Key Features:</b>\n{features_text}")

    platform_name = "GitHub" if isinstance(repo, GitHubRepository) else "GitLab"
    links = [f'• <a href="{repo.url}">{platform_name} Repository</a>']

    if ai and ai.important_links:
        links.extend(f'• <a href="{link.url}">{link.title}</a>' for link in ai.important_links)

    sections.append("🔗 <b>Links:</b>\n" + "\n".join(links))

    if tags:
        hashtags = " ".join(f"#{tag}" for tag in tags)
        sections.append(f"🏷️ <b>Tags:</b> {hashtags}")

    return "\n\n".join(sections)


def create_keyboard(keyboard_type: KeyboardType) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if keyboard_type == KeyboardType.CONFIRMATION:
        for text, action in (("✅ Confirm", PostAction.CONFIRM), ("❌ Cancel", PostAction.CANCEL)):
            builder.button(text=text, callback_data=PostCallback(action=action))
        builder.adjust(2)
        return builder.as_markup()

    if keyboard_type == KeyboardType.PREVIEW:
        for text, action in (
            ("✅ Publish", PostAction.PUBLISH),
            ("🔄 Regenerate", PostAction.REGENERATE),
            ("❌ Cancel", PostAction.CANCEL),
        ):
            builder.button(text=text, callback_data=PostCallback(action=action))
        builder.adjust(2, 1)
        return builder.as_markup()

    return builder.as_markup()


async def _validate_session(
    callback: CallbackQuery, state: FSMContext
) -> tuple[str, EnhancedRepositoryData, BytesIO] | None:
    if not (message := callback.message) or isinstance(message, InaccessibleMessage):
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
        await edit_message_text_or_caption(
            message, "❌ <b>Error</b>\n\nSession expired or missing data. Try /post again."
        )
        return None

    if not settings.channel_id:
        await edit_message_text_or_caption(
            message, "❌ <b>Error</b>\n\nChannel ID not configured."
        )
        return None

    return post_text, enhanced_data, banner_buffer


async def _handle_error(
    message: Message, state: FSMContext, error_text: str, clear_state: bool = True
) -> None:
    await edit_message_text_or_caption(message, f"❌ <b>Error</b>\n\n{error_text}")
    if clear_state:
        await state.clear()


async def _handle_publication(
    callback: CallbackQuery,
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
        return (
            "<b>Permission Error</b>\n\n"
            "Bot cannot access the channel.\n\n"
            f"<b>Error:</b> {e!s}\n\n"
            "Please check bot permissions."
        )

    banner_input = BufferedInputFile(banner_buffer.getvalue(), filename=banner_filename)
    sent_message = await callback.bot.send_photo(
        chat_id=settings.channel_id, photo=banner_input, caption=post_text
    )

    await submit(repository, sent_message.message_id)

    if callback.from_user:
        logger = get_logger(callback.bot)
        await logger.log_post_action(
            action=LogAction.POST_CREATED,
            admin_user=callback.from_user,
            repository_name=repository.name,
            repository_url=repository.url,
        )

    return "✅ <b>Post Published!</b>\n\n<i>Post sent to channel and saved to database.</i>"


async def process_post_publication(
    callback: CallbackQuery,
    enhanced_data: EnhancedRepositoryData,
    post_text: str,
    banner_buffer: BytesIO,
) -> None:
    if (
        not callback.bot
        or not callback.message
        or isinstance(callback.message, InaccessibleMessage)
    ):
        return

    repository = enhanced_data.repository
    project_name = get_project_name(enhanced_data)
    banner_filename = f"{project_name.lower().replace(' ', '_')}_banner.png"

    try:
        result_text = await _handle_publication(
            callback, post_text, banner_buffer, banner_filename, repository
        )

        if result_text:
            await callback.message.edit_caption(caption=result_text)
    except Exception as e:
        error_message = f"Failed to process publication: {e!s}"
        await callback.message.edit_caption(caption=f"❌ <b>Error</b>\n\n{error_message}")

        if callback.bot and callback.from_user:
            logger = get_logger(callback.bot)
            await logger.log_error(
                error_description=(
                    f"Post publication failed for {repository.name}: {error_message}"
                ),
                user=callback.from_user,
                extra_data={"repository_name": repository.name, "repository_url": repository.url},
            )

        raise


async def process_post_content(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData
) -> None:
    project_name = get_project_name(enhanced_data)
    await message.edit_text(
        "🎨 <b>Finalizing Content</b>\n\n<i>Formatting post and generating banner...</i>"
    )

    try:
        post_text_task = asyncio.to_thread(format_post, enhanced_data)
        banner_task = asyncio.to_thread(generate_banner, project_name)
        results = await asyncio.gather(post_text_task, banner_task, return_exceptions=True)
        post_text, banner_result = results

        if isinstance(post_text, Exception):
            raise post_text

        banner_buffer = banner_result if isinstance(banner_result, BytesIO) else None

        await state.update_data(
            enhanced_data=enhanced_data,
            post_text=str(post_text),
            banner_buffer=banner_buffer,
        )
        await state.set_state(PostStates.previewing_post)

        if banner_buffer:
            await send_successful_preview(message, banner_buffer, str(post_text))
        else:
            await _handle_error(message, state, "Banner generation failed. Try /post again.")

    except Exception:
        await _handle_error(message, state, "Content generation failed. Try /post again.")


async def send_successful_preview(
    message: Message, banner_buffer: BytesIO, post_text: str
) -> None:
    await message.edit_text("✅ <b>Post Ready</b>\n\n<i>Review and publish when ready</i>")
    banner_input = BufferedInputFile(banner_buffer.getvalue(), filename="banner.png")
    await message.answer_photo(
        photo=banner_input,
        caption=post_text,
        reply_markup=create_keyboard(KeyboardType.PREVIEW),
    )


async def process_repository_confirmation(
    message: Message, state: FSMContext, repository_url: str
) -> None:
    await message.edit_text(
        "🔄 <b>Validating Repository</b>\n\n<i>Checking posting eligibility...</i>"
    )

    try:
        async with RepositoryClient() as client:
            repo_data = await client.get_basic_repository_data(repository_url)
            can_submit_repo, last_submission = await can_submit(repo_data.id)

            if not can_submit_repo and last_submission:
                days_since = (datetime.now(tz=UTC) - last_submission.replace(tzinfo=UTC)).days
                remaining = 90 - days_since
                error_msg = f"Posted {days_since} days ago. Wait {remaining} more days to repost."
                await _handle_error(message, state, error_msg)
                return

            await message.edit_text(
                "🤖 <b>Generating AI Content</b>\n\n<i>Creating enhanced content...</i>"
            )
            enhanced_data = await client.get_enhanced_repository_data(
                repository_url,
                settings.openai_api_key.get_secret_value(),
                openai_base_url=settings.openai_base_url,
            )
            await process_post_content(message, state, enhanced_data)

    except Exception as e:
        await _handle_error(message, state, f"Processing failed: {e!s}")


@router.message(Command("post"))
async def post_command_handler(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    user_id = message.from_user.id
    await clear_user_data(state, user_id)
    await state.set_state(PostStates.waiting_for_repository_url)

    await message.reply(
        "📱 <b>New Post</b>\n\nSend a GitHub or GitLab repository URL. Use /cancel to abort."
    )


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "cancel")
async def cancel_command_handler(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    user_id = message.from_user.id
    current_state = await state.get_state()

    if not current_state:
        await message.reply(
            "❌ <b>No Active Session</b>\n\nNo post creation in progress. Use /post to start."
        )
        return

    await clear_user_data(state, user_id)

    await message.reply("❌ <b>Cancelled</b>\n\nPost creation cancelled. Use /post to start over.")


@router.message(PostStates.waiting_for_repository_url, F.text)
async def repository_url_handler(message: Message, state: FSMContext) -> None:
    if not message.text or not message.from_user:
        await message.reply(
            "❌ <b>Invalid Input</b>\n\n"
            "Please provide a valid repository URL from GitHub or GitLab."
        )
        return

    user_id = message.from_user.id
    url = message.text.strip()

    if not RepositoryClient.is_valid_repository_url(url):
        await message.reply(
            "❌ <b>Invalid URL</b>\n\n"
            "Send a valid GitHub or GitLab repository URL.\n"
            "Use /cancel to abort."
        )
        return

    await update_user_data(state, user_id, repository_url=url)
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
        "💡 Send 'cancel' to abort."
    )


@router.callback_query(PostCallback.filter(F.action == PostAction.CONFIRM))
async def confirm_post_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not (message := callback.message) or isinstance(message, InaccessibleMessage):
        return

    if not callback.from_user:
        return

    user_id = callback.from_user.id
    repository_url = await get_user_repository_url(state, user_id)

    if not repository_url:
        await _handle_error(message, state, "Session expired, please start again.")
        return

    await process_repository_confirmation(message, state, repository_url)


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE))
async def regenerate_post_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not (message := callback.message) or isinstance(message, InaccessibleMessage):
        return

    repository_url = None
    if callback.from_user:
        repository_url = await get_user_repository_url(state, callback.from_user.id)
    if not repository_url:
        await _handle_error(message, state, "Session expired, please start again.")
        return

    await message.delete()
    new_message = await message.answer("🔄 <b>Regenerating Content</b>\n\nPlease wait...")

    await state.set_state(PostStates.waiting_for_confirmation)
    await process_repository_confirmation(new_message, state, repository_url)


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH))
async def publish_post_handler(callback: CallbackQuery, state: FSMContext) -> None:
    session_data = await _validate_session(callback, state)
    if not session_data:
        await state.clear()
        return

    post_text, enhanced_data, banner_buffer = session_data
    try:
        await process_post_publication(callback, enhanced_data, post_text, banner_buffer)
    except Exception as e:
        if (message := callback.message) and not isinstance(message, InaccessibleMessage):
            await _handle_error(message, state, f"Publishing Failed: {e!s}", False)
    finally:
        if banner_buffer:
            banner_buffer.close()
        await state.clear()


@router.callback_query(PostCallback.filter(F.action == PostAction.CANCEL))
async def cancel_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not (message := callback.message) or isinstance(message, InaccessibleMessage):
        return

    if await state.get_state():
        data = await state.get_data()
        banner_buffer = data.get("banner_buffer")
        if isinstance(banner_buffer, BytesIO):
            banner_buffer.close()
        await state.clear()

    await edit_message_text_or_caption(
        message, "❌ <b>Cancelled</b>\nYou can start again with /post."
    )
    await callback.answer("Cancelled")
