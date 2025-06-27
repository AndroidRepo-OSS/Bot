# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import asyncio
import contextlib
import re
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

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
from bot.utils.enums import (
    EditAction,
    EditCallback,
    EditField,
    KeyboardType,
    PostAction,
    PostCallback,
)
from bot.utils.models import EnhancedRepositoryData, GitHubRepository, ImportantLink
from bot.utils.repository_client import RepositoryClient
from bot.utils.states import PostStates

router = Router(name="posts")

REPOSITORY_URL_PATTERN = re.compile(r"^https?://(github\.com|gitlab\.com)/[\w.-]+/[\w.-]+/?$")


class PostHandler:
    def __init__(self, enhanced_data: EnhancedRepositoryData):
        self.enhanced_data = enhanced_data
        self.repository = enhanced_data.repository
        self.ai_content = enhanced_data.ai_content

    @property
    def project_name(self) -> str:
        return (self.ai_content.project_name if self.ai_content else None) or self.repository.name

    @property
    def description(self) -> str | None:
        if self.ai_content:
            return self.ai_content.enhanced_description
        return self.repository.description

    @property
    def tags(self) -> list[str]:
        if self.ai_content:
            return self.ai_content.relevant_tags or []
        return self.repository.topics or []

    def format_post(self) -> str:
        sections = [f"<b>{self.project_name}</b>"]

        if self.description:
            sections.append(f"<i>{self.description}</i>")

        if self.ai_content and self.ai_content.key_features:
            features_text = "\n".join(f"• {feature}" for feature in self.ai_content.key_features)
            sections.append(f"✨ <b>Key Features:</b>\n{features_text}")

        platform_name = "GitHub" if isinstance(self.repository, GitHubRepository) else "GitLab"
        links = [f'• <a href="{self.repository.url}">{platform_name} Repository</a>']

        if self.ai_content and self.ai_content.important_links:
            additional_links = [
                f'• <a href="{link.url}">{link.title}</a>'
                for link in self.ai_content.important_links
            ]
            links.extend(additional_links)

        sections.append("🔗 <b>Links:</b>\n" + "\n".join(links))

        if self.tags:
            hashtags = " ".join(f"#{tag}" for tag in self.tags)
            sections.append(f"🏷️ <b>Tags:</b> {hashtags}")

        return "\n\n".join(sections)

    def update_field(self, field: EditField, new_text: str) -> None:
        if field == EditField.DESCRIPTION:
            self._update_description(new_text)
        elif field == EditField.TAGS:
            self._update_tags(new_text)
        elif field == EditField.FEATURES:
            self._update_features(new_text)
        elif field == EditField.LINKS:
            self._update_links(new_text)

    def _update_description(self, new_text: str) -> None:
        text = new_text.strip()
        if self.ai_content:
            self.ai_content.enhanced_description = text
        else:
            self.repository.description = text

    def _update_tags(self, new_text: str) -> None:
        tags = [
            tag.strip().lower().replace(" ", "_")
            for tag in re.split(r"[,\s]+", new_text.strip())
            if tag.strip()
        ]
        if self.ai_content:
            self.ai_content.relevant_tags = tags[:7]
        else:
            self.repository.topics = tags[:7]

    def _update_features(self, new_text: str) -> None:
        features = [
            line.strip().lstrip("•").strip()
            for line in new_text.replace(";", "\n").split("\n")
            if line.strip()
        ]
        if self.ai_content:
            self.ai_content.key_features = features[:4]

    def _update_links(self, new_text: str) -> None:
        links = []
        for line in new_text.strip().split("\n"):
            if ":" in line and "http" in line:
                title, url = line.split(":", 1)
                links.append(ImportantLink(title=title.strip(), url=url.strip(), type="website"))
        if self.ai_content:
            self.ai_content.important_links = links[:3]


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
        builder.button(text="✏️ Edit", callback_data=PostCallback(action=PostAction.EDIT))
        builder.button(
            text="🔄 Regenerate", callback_data=PostCallback(action=PostAction.REGENERATE)
        )
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2, 2)

    elif keyboard_type == KeyboardType.EDIT:
        builder.button(
            text="📝 Description",
            callback_data=EditCallback(action=EditAction.FIELD, field=EditField.DESCRIPTION),
        )
        builder.button(
            text="🏷️ Tags",
            callback_data=EditCallback(action=EditAction.FIELD, field=EditField.TAGS),
        )
        builder.button(
            text="⭐ Features",
            callback_data=EditCallback(action=EditAction.FIELD, field=EditField.FEATURES),
        )
        builder.button(
            text="🔗 Links",
            callback_data=EditCallback(action=EditAction.FIELD, field=EditField.LINKS),
        )
        builder.button(
            text="🔙 Back", callback_data=PostCallback(action=PostAction.BACK_TO_PREVIEW)
        )
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2, 2, 2)

    elif keyboard_type == KeyboardType.BACK_TO_EDIT:
        builder.button(text="🔙 Back", callback_data=EditCallback(action=EditAction.BACK_TO_MENU))
        builder.adjust(1)

    return builder.as_markup()


def get_field_name(field: EditField) -> str:
    return {
        EditField.DESCRIPTION: "description",
        EditField.TAGS: "tags",
        EditField.FEATURES: "features",
        EditField.LINKS: "links",
    }.get(field, "unknown")


def get_edit_message(field: EditField) -> str:
    field_name = get_field_name(field)
    return f"📝 <b>Edit {field_name.title()}</b>\n\nSend the new {field_name}:"


async def validate_and_get_data(
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

    if not post_text or not enhanced_data or not banner_buffer:
        await safe_edit_message(
            callback.message,
            "❌ <b>Error</b>\n\nSession expired or missing data. Try /post again.",
        )
        return None

    return post_text, enhanced_data, banner_buffer


async def validate_settings(callback: CallbackQuery, banner_buffer: Any) -> Settings | None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return None

    if not settings.channel_id:
        await safe_edit_message(callback.message, "❌ <b>Error</b>\n\nChannel ID not configured.")
        return None

    banner_size = len(banner_buffer.getvalue())
    if banner_size > 10 * 1024 * 1024:
        await safe_edit_message(callback, "❌ <b>Error</b>\n\nBanner too large (>10MB).")
        return None

    return settings


async def publish_immediately(
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
        await safe_edit_message(callback, error_text)
        return None

    banner_input = BufferedInputFile(banner_buffer.getvalue(), filename=banner_filename)

    sent_message = await callback.bot.send_photo(
        chat_id=settings.channel_id, photo=banner_input, caption=post_text
    )

    await submit_app(repository, sent_message.message_id)

    return "✅ <b>Post Published!</b>\n\n<i>Post sent to channel and saved to database.</i>"


class PostAlreadyScheduledError(Exception):
    pass


async def schedule_post_handler(
    scheduler: PostScheduler,
    repository: Any,
    post_text: str,
    banner_buffer: Any,
    banner_filename: str,
) -> str:
    if await has_pending_scheduled_post(repository.id):
        raise PostAlreadyScheduledError

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
    banner_buffer: Any,
    settings: Settings,
) -> None:
    if not callback.bot:
        await safe_edit_message(callback, "❌ Bot instance not available")
        return

    repository = enhanced_data.repository
    project_name = PostHandler(enhanced_data).project_name

    scheduler = PostScheduler(callback.bot, settings)
    current_time = datetime.now(UTC)
    next_slot = await scheduler.get_next_available_slot(current_time)

    banner_filename = f"{project_name.lower().replace(' ', '_')}_banner.png"

    time_diff = (next_slot - current_time).total_seconds()
    can_post_immediately = time_diff <= 60

    if can_post_immediately:
        success_text = await publish_immediately(
            callback, settings, post_text, banner_buffer, banner_filename, repository
        )
        if success_text:
            await safe_edit_message(callback, success_text)
    else:
        try:
            success_text = await schedule_post_handler(
                scheduler,
                repository,
                post_text,
                banner_buffer,
                banner_filename,
            )
            if success_text:
                await safe_edit_message(callback, success_text)
        except PostAlreadyScheduledError:
            error_text = (
                "⚠️ <b>Post Already Scheduled</b>\n\n"
                "This repository already has a post scheduled for publication.\n\n"
                "<i>To avoid spam, only one post per repository can be scheduled at a time.</i>"
            )
            await safe_edit_message(callback, error_text)


async def process_post_content(message: Message, state: FSMContext, enhanced_data) -> None:
    project_name = PostHandler(enhanced_data).project_name
    await safe_edit_message(
        message,
        "🎨 <b>Finalizing Content</b>\n\n<i>Formatting post and generating banner...</i>",
    )

    post_text_task = asyncio.create_task(asyncio.to_thread(PostHandler(enhanced_data).format_post))

    banner_task = asyncio.create_task(asyncio.to_thread(generate_banner, project_name))

    try:
        post_text, banner_buffer = await asyncio.gather(
            post_text_task, banner_task, return_exceptions=True
        )

        if isinstance(post_text, Exception):
            raise post_text
        if isinstance(banner_buffer, Exception):
            banner_generated = False
            banner_buffer = None
        else:
            banner_generated = True

    except Exception:
        await handle_error(message, state, "Content generation failed. Try /post again.")
        return

    await finalize_post_preview(
        message, state, enhanced_data, str(post_text), banner_buffer, banner_generated
    )


async def finalize_post_preview(
    message: Message,
    state: FSMContext,
    enhanced_data,
    post_text: str,
    banner_buffer,
    banner_generated: bool,
) -> None:
    await state.update_data(
        enhanced_data=enhanced_data,
        post_text=post_text,
        banner_buffer=banner_buffer if banner_generated else None,
        banner_generated=banner_generated,
    )
    await state.set_state(PostStates.previewing_post)

    if banner_generated and banner_buffer:
        await send_successful_preview(message, banner_buffer, post_text)
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


async def handle_error(message: Message, state: FSMContext, error_msg: str) -> None:
    await safe_edit_message(message, f"❌ <b>Error</b>\n\n{error_msg}")
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
            "Please provide a valid repository URL from GitHub or GitLab.\n\n"
        )
        return

    url = message.text.strip()
    if not REPOSITORY_URL_PATTERN.match(url):
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


@router.message(PostStates.editing_description, F.text)
@router.message(PostStates.editing_tags, F.text)
@router.message(PostStates.editing_features, F.text)
@router.message(PostStates.editing_links, F.text)
async def handle_edit_state_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❗ <b>Invalid Input</b>\n\nSend the new value or /cancel to abort.")
        return

    data = await state.get_data()
    enhanced_data, editing_field_str = data.get("enhanced_data"), data.get("editing_field")

    if not enhanced_data or not editing_field_str:
        await message.reply(
            "❌ <b>Session Expired</b>\n\nEdit session expired. Please start over with /post."
        )
        await state.clear()
        return

    try:
        editing_field = EditField(editing_field_str)
        PostHandler(enhanced_data).update_field(editing_field, message.text)
        await finalize_field_edit(message, state, enhanced_data, editing_field)
    except ValueError:
        await message.reply(
            "❌ <b>Invalid Field</b>\n\nAn internal error occurred. Please try again or /cancel."
        )
    except Exception:
        await message.reply(
            f"❌ <b>Update Failed</b>\n\n"
            f"Could not update {editing_field_str}. Please try again or /cancel."
        )


async def finalize_field_edit(message, state, enhanced_data, field) -> None:
    if banner_buffer := (await state.get_data()).get("banner_buffer"):
        banner_buffer.close()

    await state.update_data(enhanced_data=enhanced_data)
    new_post_text = PostHandler(enhanced_data).format_post()
    await state.update_data(post_text=new_post_text)
    await state.set_state(PostStates.previewing_post)

    await message.reply(
        f"✅ <b>{get_field_name(field).title()} Updated!</b>\n\n"
        f"Your changes have been saved.\n"
        f"The preview has been updated with your new content.\n\n"
        f"💡 You can continue editing, publish, or make further changes."
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
                await handle_error(
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
        await handle_error(callback.message, state, f"Processing failed: {e!s}")


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
    validation_result = await validate_and_get_data(callback, state)
    if not validation_result:
        return

    post_text, enhanced_data, banner_buffer = validation_result

    settings = await validate_settings(callback, banner_buffer)
    if not settings:
        return

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
        if banner_buffer:
            banner_buffer.close()

    await state.clear()


@router.callback_query(PostCallback.filter(F.action == PostAction.EDIT))
async def edit_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not callback.message or not enhanced_data:
        return

    await state.set_state(PostStates.editing_post)

    edit_text = (
        "✏️ <b>Edit Post</b>\n\n"
        "<b>Select field to update:</b>\n"
        "• Description\n"
        "• Tags\n"
        "• Features\n"
        "• Links"
    )

    await safe_edit_message(callback.message, edit_text, create_keyboard(KeyboardType.EDIT))
    await callback.answer("Edit mode activated")


@router.callback_query(PostCallback.filter(F.action == PostAction.BACK_TO_PREVIEW))
async def back_to_preview_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    data = await state.get_data()
    enhanced_data, post_text = data.get("enhanced_data"), data.get("post_text")

    if not enhanced_data or not post_text:
        return

    await state.set_state(PostStates.previewing_post)

    await callback.message.edit_caption(
        caption=post_text, reply_markup=create_keyboard(KeyboardType.PREVIEW)
    )

    await callback.answer("Returned to preview")


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


@router.callback_query(EditCallback.filter(F.action == EditAction.BACK_TO_MENU))
async def back_to_edit_menu_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: EditCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    if not (await state.get_data()).get("enhanced_data"):
        return

    await edit_post_handler(callback, state, PostCallback(action=PostAction.EDIT))
    await callback.answer("Returned to edit menu")


@router.callback_query(EditCallback.filter(F.action == EditAction.FIELD))
async def edit_field_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: EditCallback
) -> None:
    if (
        isinstance(callback.message, InaccessibleMessage)
        or not callback.message
        or not callback_data.field
    ):
        return

    enhanced_data = (await state.get_data()).get("enhanced_data")
    if not enhanced_data:
        return

    field_state_mapping = {
        EditField.DESCRIPTION: PostStates.editing_description,
        EditField.TAGS: PostStates.editing_tags,
        EditField.FEATURES: PostStates.editing_features,
        EditField.LINKS: PostStates.editing_links,
    }

    if new_state := field_state_mapping.get(callback_data.field):
        await state.set_state(new_state)
        await state.update_data(editing_field=get_field_name(callback_data.field))

        edit_text = get_edit_message(callback_data.field)
        keyboard = create_keyboard(KeyboardType.BACK_TO_EDIT)

        await safe_edit_message(callback.message, edit_text, keyboard)
        await callback.answer(f"Edit {get_field_name(callback_data.field)} mode activated")
