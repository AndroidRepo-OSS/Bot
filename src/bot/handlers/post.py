# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import logging
import re
from enum import Enum

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.utils.cache import repository_cache
from bot.utils.github_client import GitHubClient
from bot.utils.models import AIGeneratedContent, EnhancedRepositoryData, GitHubRepository

logger = logging.getLogger(__name__)
router = Router(name="post")

GITHUB_URL_PATTERN = re.compile(r"^https?://github\.com/[\w.-]+/[\w.-]+/?$")


class PostStates(StatesGroup):
    """
    Finite state machine states for the post creation workflow in the bot.

    This class defines all the states used during the process of creating,
    editing, previewing, and confirming a post. Each state represents a
    specific step or field in the workflow, allowing for granular control
    over user interactions.
    """

    waiting_for_github_url = State()
    """State when the bot is waiting for the user to provide a GitHub repository URL."""

    waiting_for_confirmation = State()
    """State when the bot is waiting for the user to confirm the final post before publishing."""

    previewing_post = State()
    """State when the user is previewing the generated post with all its details."""

    editing_post = State()
    """State when the user is in the main editing mode, choosing which field to modify."""

    editing_description = State()
    """State when the user is editing the description field of the post."""

    editing_tags = State()
    """State when the user is editing the tags field of the post."""

    editing_features = State()
    """State when the user is editing the features field of the post."""

    editing_links = State()
    """State when the user is editing the links field of the post."""


class PostAction(Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    FORCE_CONTINUE = "force_continue"
    PUBLISH = "publish"
    EDIT = "edit"
    REGENERATE = "regenerate"
    BACK_TO_PREVIEW = "back_to_preview"


class EditField(Enum):
    DESCRIPTION = "description"
    TAGS = "tags"
    FEATURES = "features"
    LINKS = "links"


class EditAction(Enum):
    FIELD = "field"
    BACK_TO_MENU = "back_to_menu"


class KeyboardType(Enum):
    CONFIRMATION = "confirmation"
    WARNING = "warning"
    PREVIEW = "preview"
    EDIT = "edit"
    BACK_TO_EDIT = "back_to_edit"


class PostCallback(CallbackData, prefix="post"):
    action: PostAction


class EditCallback(CallbackData, prefix="edit"):
    action: EditAction
    field: EditField | None = None


def create_keyboard(keyboard_type: KeyboardType) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if keyboard_type == KeyboardType.CONFIRMATION:
        builder.button(text="✅ Proceed", callback_data=PostCallback(action=PostAction.CONFIRM))
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2)

    elif keyboard_type == KeyboardType.WARNING:
        builder.button(
            text="✅ Continue",
            callback_data=PostCallback(action=PostAction.FORCE_CONTINUE),
        )
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2)

    elif keyboard_type == KeyboardType.PREVIEW:
        builder.button(text="✅ Publish", callback_data=PostCallback(action=PostAction.PUBLISH))
        builder.button(text="✏️ Edit", callback_data=PostCallback(action=PostAction.EDIT))
        builder.button(
            text="🔄 Regenerate",
            callback_data=PostCallback(action=PostAction.REGENERATE),
        )
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2, 2)

    elif keyboard_type == KeyboardType.EDIT:
        edit_fields = [
            ("📝 Description", EditField.DESCRIPTION),
            ("🏷️ Tags", EditField.TAGS),
            ("⭐ Features", EditField.FEATURES),
            ("🔗 Links", EditField.LINKS),
        ]

        for text, field in edit_fields:
            builder.button(
                text=text, callback_data=EditCallback(action=EditAction.FIELD, field=field)
            )

        builder.button(
            text="🔙 Back",
            callback_data=PostCallback(action=PostAction.BACK_TO_PREVIEW),
        )
        builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
        builder.adjust(2, 2, 2)

    elif keyboard_type == KeyboardType.BACK_TO_EDIT:
        builder.button(text="🔙 Back", callback_data=EditCallback(action=EditAction.BACK_TO_MENU))

    return builder.as_markup()


def _is_android_related(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> bool:
    android_indicators = [
        "android",
        "kotlin",
        "java",
        "gradle",
        "apk",
        "jetpack",
        "compose",
        "material",
    ]

    text_sources = [
        " ".join(repository.topics).lower(),
        (repository.description or "").lower(),
        (
            " ".join(ai_content.relevant_tags).lower()
            if ai_content and ai_content.relevant_tags
            else ""
        ),
    ]

    combined_text = " ".join(text_sources)
    return any(indicator in combined_text for indicator in android_indicators)


def _create_progress_message(step: int, total_steps: int, step_name: str, repo_name: str) -> str:
    progress_bar = "▓" * step + "░" * (total_steps - step)
    percentage = int((step / total_steps) * 100)

    return (
        f"🔄 <b>Processing Repository</b>\n\n"
        f"<b>Repository:</b> {repo_name}\n"
        f"<b>Progress:</b> {percentage}% [{progress_bar}]\n"
        f"<b>Current Step:</b> {step_name}\n\n"
        "<i>Please wait...</i>"
    )


async def _update_progress(
    message: Message, step: int, total_steps: int, step_name: str, repo_name: str
) -> None:
    try:
        progress_text = _create_progress_message(step, total_steps, step_name, repo_name)
        await message.edit_text(progress_text)
    except Exception as e:
        logger.warning("Failed to update progress message: %s", e)


@router.message(Command("post"))
async def post_command_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(PostStates.waiting_for_github_url)

    await message.reply(
        "📱 <b>Android Repo Post Creator</b>\n"
        "Send a GitHub repository URL to generate a post.\n\n"
        "Example: https://github.com/user/repository\n"
        "Use /cancel to abort."
    )


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "cancel")
async def cancel_command_handler(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()

    if current_state is None:
        await message.reply(
            "❌ <b>No active session</b>\n"
            "You don't have any post creation in progress.\n"
            "Send /post to begin."
        )
        return

    await state.clear()

    await message.reply(
        "❌ <b>Cancelled</b>\nYour post creation was cancelled.\nSend /post to start over."
    )


@router.message(PostStates.waiting_for_github_url, F.text)
async def github_url_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply(
            "❌ <b>Invalid input</b>\n"
            "Send a valid GitHub repository URL.\n"
            "Example: https://github.com/user/repository"
        )
        return

    url = message.text.strip()
    if not GITHUB_URL_PATTERN.match(url):
        await message.reply(
            "❌ <b>Invalid GitHub URL</b>\n\n"
            "Please provide a valid GitHub repository URL.\n\n"
            "<i>Example: https://github.com/user/repository</i>\n\n"
            "💡 Use /cancel to cancel the post creation."
        )
        return

    await state.update_data(github_url=url)
    await state.set_state(PostStates.waiting_for_confirmation)

    await message.reply(
        f"📋 <b>Post Preview</b>\n\n"
        f"<b>Repository:</b> <code>{url}</code>\n\n"
        f"Do you want to proceed with creating the post?",
        reply_markup=create_keyboard(KeyboardType.CONFIRMATION),
    )


@router.message(PostStates.waiting_for_github_url)
async def invalid_github_url_handler(message: Message) -> None:
    await message.reply(
        "❌ <b>Invalid input</b>\n"
        "Send a valid GitHub URL or /cancel to abort.\n"
        "Example: https://github.com/user/repository"
    )


@router.callback_query(PostCallback.filter(F.action == PostAction.CONFIRM))
async def confirm_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    github_url = data.get("github_url")

    if not callback.message or not github_url:
        return

    repo_name = github_url.split("/")[-1]
    total_steps = 4

    await callback.message.edit_text(
        _create_progress_message(1, total_steps, "Fetching repository data", repo_name)
    )

    try:
        settings = Settings()  # type: ignore

        await _update_progress(
            callback.message, 2, total_steps, "Analyzing repository content", repo_name
        )

        async with GitHubClient() as client:
            enhanced_data = await client.get_enhanced_repository_data(
                github_url,
                settings.openai_api_key.get_secret_value(),
                settings.openai_base_url,
            )

        repository = enhanced_data.repository
        ai_content = enhanced_data.ai_content

        await _update_progress(
            callback.message, 3, total_steps, "Generating post content", repo_name
        )

        if not _is_android_related(repository, ai_content):
            await callback.message.edit_text(
                f"⚠️ <b>Non-Android Repository Detected</b>\n\n"
                f"<b>Repository:</b> {repository.name}\n"
                f"<b>Warning:</b> This repository doesn't appear to be Android-related.\n\n"
                f"The Android Repository channel focuses on Android apps, tools, and utilities. "
                f"This project may not be suitable for the channel.\n\n"
                f"Do you still want to continue?"
            )

            await callback.message.edit_reply_markup(
                reply_markup=create_keyboard(KeyboardType.WARNING)
            )
            await state.update_data(enhanced_data=enhanced_data)
            return

        await _update_progress(
            callback.message, 4, total_steps, "Finalizing post preview", repo_name
        )

        await _show_post_preview(callback.message, state, enhanced_data)

    except Exception as e:
        logger.error("Error processing repository %s: %s", github_url, e)
        await callback.message.edit_text(
            f"❌ <b>Error Processing Repository</b>\n\n"
            f"Failed to process: <code>{github_url}</code>\n\n"
            f"<b>Error:</b> <code>{str(e)[:200]}...</code>\n\n"
            f"This could be due to:\n"
            f"• Repository is private or doesn't exist\n"
            f"• GitHub API rate limits\n"
            f"• OpenAI API issues\n"
            f"• Network connectivity problems\n\n"
        )
        await state.clear()

    await callback.answer("Processing completed!")


@router.callback_query(PostCallback.filter(F.action == PostAction.FORCE_CONTINUE))
async def force_continue_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not callback.message or not enhanced_data:
        return

    await _show_post_preview(callback.message, state, enhanced_data)
    await callback.answer("Continuing with post creation...")


async def _show_post_preview(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData
) -> None:
    repository = enhanced_data.repository
    ai_content = enhanced_data.ai_content

    post_text = _format_enhanced_post(repository, ai_content)

    await state.update_data(enhanced_data=enhanced_data, post_text=post_text)
    await state.set_state(PostStates.previewing_post)

    android_status = (
        "✅ Android-related" if _is_android_related(repository, ai_content) else "⚠️ Non-Android"
    )

    preview_text = (
        f"📋 <b>Post Preview</b>\n\n"
        f"<b>Repository:</b> {repository.name}\n"
        f"<b>Author:</b> {repository.owner}\n"
        f"<b>Status:</b> {android_status}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{post_text}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"<i>Review your post above. You can edit it, regenerate it, "
        f"or publish it to the channel.</i>"
    )

    try:
        await message.edit_text(
            preview_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )
    except TelegramBadRequest:
        await message.answer(
            preview_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH))
async def publish_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.bot:
        return

    data = await state.get_data()
    post_text = data.get("post_text")
    enhanced_data = data.get("enhanced_data")

    if not callback.message or not post_text or not enhanced_data:
        return

    settings = Settings()  # type: ignore

    try:
        await callback.bot.send_message(chat_id=settings.channel_id, text=post_text)

        await callback.message.edit_text(
            f"✅ <b>Post Published Successfully!</b>\n\n"
            f"Repository: {enhanced_data.repository.name}\n"
            f"Author: {enhanced_data.repository.owner}\n\n"
            f"The post has been sent to the configured channel."
        )

        await callback.answer("Post published to channel successfully!")

    except Exception as e:
        logger.exception("Failed to publish post to channel: %s", e)

        await callback.message.edit_text(
            f"❌ <b>Failed to Publish Post</b>\n\n"
            f"Repository: {enhanced_data.repository.name}\n"
            f"Author: {enhanced_data.repository.owner}\n\n"
            f"Error: {e!s}\n\n"
            f"Please check the channel ID configuration and bot permissions."
        )

        await callback.answer("Failed to publish post. Check logs for details.", show_alert=True)

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

    await callback.message.edit_text(
        f"✏️ <b>Edit Post</b>\n"
        f"Repository: {enhanced_data.repository.name}\n\n"
        f"Select a field to update:\n"
        f"• Description\n"
        f"• Tags\n"
        f"• Features\n"
        f"• Links",
        reply_markup=create_keyboard(KeyboardType.EDIT),
    )

    await callback.answer("Edit mode activated!")


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE))
async def regenerate_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    github_url = data.get("github_url")

    if not callback.message or not github_url:
        return

    repository_cache.delete(github_url)

    await callback.message.edit_text(
        "🔄 <b>Regenerating</b>\nClearing cache and generating new content.\n<i>Please wait...</i>"
    )

    await state.set_state(PostStates.waiting_for_confirmation)

    await confirm_post_handler(callback, state)


@router.callback_query(PostCallback.filter(F.action == PostAction.BACK_TO_PREVIEW))
async def back_to_preview_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not callback.message or not enhanced_data:
        return

    await _show_post_preview(callback.message, state, enhanced_data)
    await callback.answer("Returned to preview!")


@router.callback_query(PostCallback.filter(F.action == PostAction.CANCEL))
async def cancel_callback_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    if not callback.message:
        return

    await callback.message.edit_text(
        "❌ <b>Post Creation Cancelled</b>\n\nYou can start again anytime with /post command."
    )

    current_state = await state.get_state()
    if current_state:
        await state.clear()

    await callback.answer("Post cancelled!")


def _format_enhanced_post(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> str:
    description = (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description
    )
    tags_to_show = (
        ai_content.relevant_tags[:5]
        if ai_content and ai_content.relevant_tags
        else repository.topics[:5]
    )

    post_text = f"<b>{repository.name}</b>\n\n"

    if description:
        post_text += f"<i>{description}</i>\n\n"

    if ai_content and ai_content.key_features:
        post_text += "<b>Key Features:</b>\n"
        for feature in ai_content.key_features:
            post_text += f"• {feature}\n"
        post_text += "\n"

    links = [f'• <a href="{repository.url}">GitHub Repository</a>']

    if ai_content and ai_content.important_links:
        additional_links = [
            f'• <a href="{link["url"]}">{link["title"]}</a>'
            for link in ai_content.important_links[:3]
        ]
        links.extend(additional_links)

    if links:
        post_text += "<b>Links:</b>\n"
        for link in links:
            post_text += f"{link}\n"
        post_text += "\n"

    post_text += f"<b>Author:</b> <code>{repository.owner}</code>\n"

    if tags_to_show:
        hashtags = " ".join(f"#{tag}" for tag in tags_to_show)
        post_text += f"<b>Tags:</b> {hashtags}\n"

    post_text += "<b>Follow:</b> @AndroidRepo // <b>Join:</b> @AndroidRepo_chat"

    return post_text


def _get_post_description(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> str | None:
    return (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description
    )


def _get_post_tags(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> list[str]:
    return (
        ai_content.relevant_tags[:5]
        if ai_content and ai_content.relevant_tags
        else repository.topics[:5]
    )


@router.callback_query(EditCallback.filter(F.action == EditAction.FIELD))
async def edit_field_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: EditCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not callback.message or not enhanced_data or not callback_data.field:
        return

    field_state_mapping = {
        EditField.DESCRIPTION: PostStates.editing_description,
        EditField.TAGS: PostStates.editing_tags,
        EditField.FEATURES: PostStates.editing_features,
        EditField.LINKS: PostStates.editing_links,
    }

    new_state = field_state_mapping.get(callback_data.field)
    if new_state:
        await state.set_state(new_state)
        await state.update_data(editing_field=callback_data.field.value)

    field_handlers = {
        EditField.DESCRIPTION: _handle_description_edit,
        EditField.TAGS: _handle_tags_edit,
        EditField.FEATURES: _handle_features_edit,
        EditField.LINKS: _handle_links_edit,
    }

    handler = field_handlers.get(callback_data.field)
    if handler:
        await handler(callback, enhanced_data)
    await callback.answer(f"Edit {callback_data.field.value} mode activated!")


async def _handle_description_edit(
    callback: CallbackQuery, enhanced_data: EnhancedRepositoryData
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    if not callback.message:
        return

    current_description = _get_post_description(enhanced_data.repository, enhanced_data.ai_content)

    await callback.message.edit_text(
        f"📝 <b>Edit Description</b>\n\n"
        f"<b>Current Description:</b>\n"
        f"<i>{current_description or 'No description available'}</i>\n\n"
        f"Send me the new description for this post, or use /cancel to abort editing.\n\n"
        f"<b>Tips:</b>\n"
        f"• Keep it 2-3 sentences\n"
        f"• Focus on user benefits\n"
        f"• Explain what the app/tool does\n"
        f"• Avoid technical jargon",
        reply_markup=create_keyboard(KeyboardType.BACK_TO_EDIT),
    )


async def _handle_tags_edit(
    callback: CallbackQuery, enhanced_data: EnhancedRepositoryData
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    if not callback.message:
        return

    current_tags = _get_post_tags(enhanced_data.repository, enhanced_data.ai_content)
    current_tags_text = (
        " ".join(f"#{tag}" for tag in current_tags) if current_tags else "No tags available"
    )

    await callback.message.edit_text(
        f"🏷️ <b>Edit Tags</b>\n\n"
        f"<b>Current Tags:</b>\n"
        f"{current_tags_text}\n\n"
        f"Send me the new tags separated by spaces or commas.\n\n"
        f"<b>Example:</b> media player video audio streaming\n\n"
        f"<b>Tips:</b>\n"
        f"• Use underscores for multi-word tags (media_player)\n"
        f"• 5-7 tags maximum\n"
        f"• Focus on functionality and category\n"
        f"• Avoid generic tags like 'android' or 'app'",
        reply_markup=create_keyboard(KeyboardType.BACK_TO_EDIT),
    )


async def _handle_features_edit(
    callback: CallbackQuery, enhanced_data: EnhancedRepositoryData
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    if not callback.message:
        return

    current_features = enhanced_data.ai_content.key_features if enhanced_data.ai_content else []
    features_text = (
        "\n".join(f"• {feature}" for feature in current_features)
        if current_features
        else "No features available"
    )

    await callback.message.edit_text(
        f"⭐ <b>Edit Key Features</b>\n\n"
        f"<b>Current Features:</b>\n"
        f"{features_text}\n\n"
        f"Send me the new key features, one per line or separated by semicolons.\n\n"
        f"<b>Example:</b>\n"
        f"Supports all video formats\n"
        f"Custom playback controls\n"
        f"Offline viewing capability\n\n"
        f"<b>Tips:</b>\n"
        f"• 3-4 features maximum\n"
        f"• Focus on user benefits\n"
        f"• Be specific and clear\n"
        f"• Highlight unique selling points",
        reply_markup=create_keyboard(KeyboardType.BACK_TO_EDIT),
    )


async def _handle_links_edit(
    callback: CallbackQuery, enhanced_data: EnhancedRepositoryData
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    if not callback.message:
        return

    current_links = enhanced_data.ai_content.important_links if enhanced_data.ai_content else []
    links_text = (
        "\n".join(f"• {link['title']}: {link['url']}" for link in current_links)
        if current_links
        else "No additional links available"
    )

    await callback.message.edit_text(
        f"🔗 <b>Edit Important Links</b>\n\n"
        f"<b>Current Links:</b>\n"
        f"{links_text}\n\n"
        f"Send me new links in this format:\n"
        f"<b>Example:</b>\n"
        f"Download App: https://play.google.com/store/apps/details?id=com.app\n"
        f"Official Website: https://www.example.com\n"
        f"User Guide: https://guide.example.com\n\n"
        f"<b>Tips:</b>\n"
        f"• 2-3 links maximum\n"
        f"• Include download links\n"
        f"• Add documentation if available\n"
        f"• Verify all URLs work",
        reply_markup=create_keyboard(KeyboardType.BACK_TO_EDIT),
    )


def _update_description(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    if enhanced_data.ai_content:
        enhanced_data.ai_content.enhanced_description = new_text.strip()
    else:
        enhanced_data.repository.description = new_text.strip()


def _update_tags(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    tags = re.split(r"[,\s]+", new_text.strip())
    tags = [tag.strip().lower().replace(" ", "_") for tag in tags if tag.strip()]

    if enhanced_data.ai_content:
        enhanced_data.ai_content.relevant_tags = tags[:7]
    else:
        enhanced_data.repository.topics = tags[:7]


def _update_features(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    features = [
        line.strip().lstrip("•").strip()
        for line in new_text.replace(";", "\n").split("\n")
        if line.strip()
    ]

    if enhanced_data.ai_content:
        enhanced_data.ai_content.key_features = features[:4]


def _update_links(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    links = []
    for line in new_text.strip().split("\n"):
        if ":" in line and "http" in line:
            title, url = line.split(":", 1)
            links.append({"title": title.strip(), "url": url.strip(), "type": "custom"})

    if enhanced_data.ai_content:
        enhanced_data.ai_content.important_links = links[:3]


@router.message(PostStates.editing_description, F.text)
async def handle_description_edit(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❗ Please send the new description or /cancel to abort.")
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not enhanced_data:
        await message.reply("❌ Edit session expired. Please start over with /post")
        await state.clear()
        return

    try:
        _update_description(enhanced_data, message.text)
        await _finalize_field_edit(message, state, enhanced_data, "description")
    except Exception as e:
        await _handle_edit_error(message, e, "description")


@router.message(PostStates.editing_tags, F.text)
async def handle_tags_edit(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❗ Please send new tags or /cancel to abort.")
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not enhanced_data:
        await message.reply("❌ Edit session expired. Please start over with /post")
        await state.clear()
        return

    try:
        _update_tags(enhanced_data, message.text)
        await _finalize_field_edit(message, state, enhanced_data, "tags")
    except Exception as e:
        await _handle_edit_error(message, e, "tags")


@router.message(PostStates.editing_features, F.text)
async def handle_features_edit(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❗ Please send new features or /cancel to abort.")
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not enhanced_data:
        await message.reply("❌ Edit session expired. Please start over with /post")
        await state.clear()
        return

    try:
        _update_features(enhanced_data, message.text)
        await _finalize_field_edit(message, state, enhanced_data, "features")
    except Exception as e:
        await _handle_edit_error(message, e, "features")


@router.message(PostStates.editing_links, F.text)
async def handle_links_edit(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❗ Please send new links or /cancel to abort.")
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not enhanced_data:
        await message.reply("❌ Edit session expired. Please start over with /post")
        await state.clear()
        return

    try:
        _update_links(enhanced_data, message.text)
        await _finalize_field_edit(message, state, enhanced_data, "links")
    except Exception as e:
        await _handle_edit_error(message, e, "links")


@router.message(PostStates.editing_description)
async def handle_invalid_description_input(message: Message) -> None:
    await message.reply("❗ Send the description text or /cancel to abort editing.")


@router.message(PostStates.editing_tags)
async def handle_invalid_tags_input(message: Message) -> None:
    await message.reply("❗ Send tags text or /cancel to abort editing.")


@router.message(PostStates.editing_features)
async def handle_invalid_features_input(message: Message) -> None:
    await message.reply("❗ Send features text or /cancel to abort editing.")


@router.message(PostStates.editing_links)
async def handle_invalid_links_input(message: Message) -> None:
    await message.reply("❗ Send links text or /cancel to abort editing.")


async def _finalize_field_edit(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData, field_name: str
) -> None:
    await state.update_data(enhanced_data=enhanced_data)

    new_post_text = _format_enhanced_post(enhanced_data.repository, enhanced_data.ai_content)
    await state.update_data(post_text=new_post_text)

    await message.reply(
        f"✅ <b>{field_name.title()} updated!</b>\nYour changes are saved. Returning to preview..."
    )

    await _show_post_preview(message, state, enhanced_data)


async def _handle_edit_error(message: Message, error: Exception, field_name: str) -> None:
    logger.error("Error updating post %s: %s", field_name, error)
    await message.reply(
        f"❌ <b>Error updating {field_name.title()}</b>\n{error!s}\nPlease try again or /cancel."
    )


@router.callback_query(EditCallback.filter(F.action == EditAction.BACK_TO_MENU))
async def back_to_edit_menu_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: EditCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not callback.message or not enhanced_data:
        return

    await edit_post_handler(callback, state, PostCallback(action=PostAction.EDIT))
    await callback.answer("Returned to edit menu!")
