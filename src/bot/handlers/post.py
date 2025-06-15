# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import logging
import re
from enum import Enum

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.states import PostStates
from bot.utils.cache import repository_cache
from bot.utils.github_client import GitHubClient
from bot.utils.models import AIGeneratedContent, EnhancedRepositoryData, GitHubRepository

logger = logging.getLogger(__name__)

router = Router(name="post")


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


class PostCallback(CallbackData, prefix="post"):
    action: PostAction


class EditCallback(CallbackData, prefix="edit"):
    action: EditAction
    field: EditField | None = None


GITHUB_URL_PATTERN = re.compile(r"^https?://github\.com/[\w.-]+/[\w.-]+/?$")

INVALID_URL_MESSAGE = (
    "❌ <b>Invalid Input</b>\n\n"
    "Please send a valid GitHub repository URL as text.\n\n"
    "<i>Example: https://github.com/user/repository</i>"
)

POST_CANCELLED_MESSAGE = (
    "❌ <b>Post Creation Cancelled</b>\n\n"
    "The post creation has been cancelled successfully.\n\n"
    "You can start again anytime with /post command."
)


def create_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm", callback_data=PostCallback(action=PostAction.CONFIRM))
    builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
    builder.adjust(2)
    return builder.as_markup()


def create_warning_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Continue Anyway", callback_data=PostCallback(action=PostAction.FORCE_CONTINUE)
    )
    builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
    builder.adjust(2)
    return builder.as_markup()


def create_preview_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Publish Post", callback_data=PostCallback(action=PostAction.PUBLISH))
    builder.button(text="✏️ Edit Post", callback_data=PostCallback(action=PostAction.EDIT))
    builder.button(text="🔄 Regenerate", callback_data=PostCallback(action=PostAction.REGENERATE))
    builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
    builder.adjust(2, 2)
    return builder.as_markup()


def create_edit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    edit_fields = [
        ("📝 Edit Description", EditField.DESCRIPTION),
        ("🏷️ Edit Tags", EditField.TAGS),
        ("⭐ Edit Features", EditField.FEATURES),
        ("🔗 Edit Links", EditField.LINKS),
    ]

    for text, field in edit_fields:
        builder.button(text=text, callback_data=EditCallback(action=EditAction.FIELD, field=field))

    builder.button(
        text="🔙 Back to Preview", callback_data=PostCallback(action=PostAction.BACK_TO_PREVIEW)
    )
    builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
    builder.adjust(2, 2, 2)
    return builder.as_markup()


def create_back_to_edit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔙 Back to Edit Menu", callback_data=EditCallback(action=EditAction.BACK_TO_MENU)
    )
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
        "📱 <b>Android Repository Post Creator</b>\n\n"
        "Please send me the GitHub repository URL you want to create a post for.\n\n"
        "<i>Example: https://github.com/user/repository</i>\n\n"
        "💡 Use /cancel to cancel the post creation at any time."
    )


@router.message(Command("cancel"))
@router.message(Command("cancel"), PostStates.waiting_for_github_url)
@router.message(Command("cancel"), PostStates.waiting_for_confirmation)
async def cancel_command_handler(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()

    if current_state is None:
        await message.reply(
            "❌ <b>No Active Post Creation</b>\n\n"
            "There's no post creation in progress to cancel.\n\n"
            "Use /post to start creating a new post."
        )
        return

    await state.clear()
    await message.reply(POST_CANCELLED_MESSAGE)


@router.message(PostStates.waiting_for_github_url, F.text)
async def github_url_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply(INVALID_URL_MESSAGE)
        return

    url = message.text.strip()

    if not GITHUB_URL_PATTERN.match(url):
        await message.reply(
            "❌ <b>Invalid GitHub URL</b>\n\n"
            "Please provide a valid GitHub repository URL.\n\n"
            "<i>Example: https://github.com/user/repository</i>"
        )
        return

    await state.update_data(github_url=url)
    await state.set_state(PostStates.waiting_for_confirmation)

    await message.reply(
        f"📋 <b>Post Preview</b>\n\n"
        f"<b>Repository:</b> <code>{url}</code>\n\n"
        f"Do you want to proceed with creating the post?",
        reply_markup=create_confirmation_keyboard(),
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

            await callback.message.edit_reply_markup(reply_markup=create_warning_keyboard())
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
            f"Please try again later or check the repository URL."
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

    await message.edit_text(
        f"📋 <b>Post Preview</b>\n\n"
        f"<b>Repository:</b> {repository.name}\n"
        f"<b>Author:</b> {repository.owner}\n"
        f"<b>Status:</b> {android_status}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{post_text}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"<i>Review your post above. You can edit it, regenerate it, "
        f"or publish it to the channel.</i>",
        reply_markup=create_preview_keyboard(),
    )


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH))
async def publish_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    post_text = data.get("post_text")
    enhanced_data = data.get("enhanced_data")

    if not callback.message or not post_text or not enhanced_data:
        return

    await callback.message.edit_text(
        f"✅ <b>Post Published Successfully!</b>\n\n"
        f"<b>Repository:</b> {enhanced_data.repository.name}\n"
        f"<b>Author:</b> {enhanced_data.repository.owner}\n\n"
        f"Your post has been formatted and is ready to be shared in the "
        f"Android Repository channel.\n\n"
        f"<i>Copy the formatted post below and share it manually in the channel:</i>\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{post_text}\n"
        f"━━━━━━━━━━━━━━━━"
    )

    await state.clear()
    await callback.answer("Post published successfully!")


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
        f"✏️ <b>Edit Post Content</b>\n\n"
        f"<b>Repository:</b> {enhanced_data.repository.name}\n\n"
        f"Choose what you'd like to edit:\n\n"
        f"• <b>Description:</b> Main post description\n"
        f"• <b>Tags:</b> Repository tags/hashtags\n"
        f"• <b>Features:</b> Key features list\n"
        f"• <b>Links:</b> Additional important links\n\n"
        f"<i>Select an option below to customize your post:</i>",
        reply_markup=create_edit_keyboard(),
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
        "🔄 <b>Regenerating Post Content</b>\n\n"
        "Clearing cache and generating fresh content...\n\n"
        "<i>Please wait while we create a new version of your post.</i>"
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

    field_handlers = {
        EditField.DESCRIPTION: _handle_description_edit,
        EditField.TAGS: _handle_tags_edit,
        EditField.FEATURES: _handle_features_edit,
        EditField.LINKS: _handle_links_edit,
    }

    handler = field_handlers.get(callback_data.field)
    if handler:
        await handler(callback, enhanced_data)

    await state.update_data(editing_field=callback_data.field.value)
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
        reply_markup=create_back_to_edit_keyboard(),
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
        reply_markup=create_back_to_edit_keyboard(),
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
        reply_markup=create_back_to_edit_keyboard(),
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
        f"<code>Title: URL</code>\n\n"
        f"<b>Example:</b>\n"
        f"Download App: https://play.google.com/store/apps/details?id=com.app\n"
        f"Official Website: https://www.example.com\n"
        f"User Guide: https://guide.example.com\n\n"
        f"<b>Tips:</b>\n"
        f"• 2-3 links maximum\n"
        f"• Include download links\n"
        f"• Add documentation if available\n"
        f"• Verify all URLs work",
        reply_markup=create_back_to_edit_keyboard(),
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


@router.message(PostStates.editing_post, F.text)
async def handle_post_edit(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")
    editing_field = data.get("editing_field")

    if not enhanced_data or not editing_field:
        await message.reply("❌ Edit session expired. Please start over with /post")
        await state.clear()
        return

    try:
        if editing_field == "description":
            _update_description(enhanced_data, message.text)
        elif editing_field == "tags":
            _update_tags(enhanced_data, message.text)
        elif editing_field == "features":
            _update_features(enhanced_data, message.text)
        elif editing_field == "links":
            _update_links(enhanced_data, message.text)

        await state.update_data(enhanced_data=enhanced_data)

        new_post_text = _format_enhanced_post(enhanced_data.repository, enhanced_data.ai_content)
        await state.update_data(post_text=new_post_text)

        await message.reply(
            f"✅ <b>{editing_field.title()} Updated Successfully!</b>\n\n"
            f"Your changes have been applied to the post.\n\n"
            f"<i>Returning to preview...</i>"
        )

        await _show_post_preview(message, state, enhanced_data)

    except Exception as e:
        logger.error("Error updating post %s: %s", editing_field, e)
        await message.reply(
            f"❌ <b>Error Updating {editing_field.title()}</b>\n\n"
            f"Failed to update the {editing_field}. Please try again or go back to preview.\n\n"
            f"Error: <code>{e!r}</code>"
        )


@router.message(Command("cancel"), PostStates.editing_post)
async def cancel_edit_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if enhanced_data:
        await _show_post_preview(message, state, enhanced_data)
        await message.reply("✅ Edit cancelled. Returned to post preview.")
    else:
        await state.clear()
        await message.reply(POST_CANCELLED_MESSAGE)


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


@router.message(PostStates.waiting_for_github_url)
async def invalid_github_url_handler(message: Message) -> None:
    await message.reply(f"{INVALID_URL_MESSAGE}\n\n💡 Use /cancel to cancel the post creation.")
