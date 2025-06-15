# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import re
from enum import Enum
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.utils.banner_generator import generate_banner
from bot.utils.cache import repository_cache
from bot.utils.github_client import GitHubClient
from bot.utils.models import AIGeneratedContent, EnhancedRepositoryData, GitHubRepository

router = Router(name="post")

GITHUB_URL_PATTERN = re.compile(r"^https?://github\.com/[\w.-]+/[\w.-]+/?$")


class PostStates(StatesGroup):
    waiting_for_github_url = State()
    waiting_for_confirmation = State()
    previewing_post = State()
    editing_post = State()
    editing_description = State()
    editing_tags = State()
    editing_features = State()
    editing_links = State()


class PostAction(Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
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

    match keyboard_type:
        case KeyboardType.CONFIRMATION:
            builder.button(
                text="✅ Confirm", callback_data=PostCallback(action=PostAction.CONFIRM)
            )
            builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
            builder.adjust(2)

        case KeyboardType.PREVIEW:
            builder.button(
                text="✅ Publish", callback_data=PostCallback(action=PostAction.PUBLISH)
            )
            builder.button(text="✏️ Edit", callback_data=PostCallback(action=PostAction.EDIT))
            builder.button(
                text="🔄 Regenerate", callback_data=PostCallback(action=PostAction.REGENERATE)
            )
            builder.button(text="❌ Cancel", callback_data=PostCallback(action=PostAction.CANCEL))
            builder.adjust(2, 2)

        case KeyboardType.EDIT:
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

        case KeyboardType.BACK_TO_EDIT:
            builder.button(
                text="🔙 Back", callback_data=EditCallback(action=EditAction.BACK_TO_MENU)
            )
            builder.adjust(1)

    return builder.as_markup()


async def try_edit_message(
    message: Message, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=markup)
            return

        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return

        await message.answer(text, reply_markup=markup)


def cleanup_banner(path: str | None) -> None:
    if path and Path(path).exists():
        Path(path).unlink()


@router.message(Command("post"))
async def post_command_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(PostStates.waiting_for_github_url)

    await message.reply(
        "� <b>Repository Post Creator</b>\n"
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

    data = await state.get_data()
    cleanup_banner(data.get("banner_path"))
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
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    data = await state.get_data()
    github_url = data.get("github_url")
    if not github_url:
        return

    repo_name = github_url.split("/")[-1]

    await callback.message.edit_text(
        f"🔄 <b>Processing Repository</b>\n\n"
        f"<b>Repository:</b> {repo_name}\n"
        f"<i>Please wait while we fetch and analyze the repository...</i>"
    )

    try:
        settings = Settings()  # type: ignore

        async with GitHubClient() as client:
            enhanced_data = await client.get_enhanced_repository_data(
                github_url,
                settings.openai_api_key.get_secret_value(),
                settings.openai_base_url,
            )

        await show_post_preview(callback.message, state, enhanced_data)

    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Error Processing Repository</b></b>\n\n"
            f"<code>{github_url}</code>\n\n"
            f"<b>Error:</b> <code>{str(e)[:200]}...</code>"
        )
        await state.clear()

    await callback.answer("Processing completed!")


async def show_post_preview(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData
) -> None:
    repository = enhanced_data.repository
    ai_content = enhanced_data.ai_content

    post_text = format_enhanced_post(repository, ai_content)

    banner_generated = False
    banner_path = None

    banner_filename = f"{repository.name.lower().replace(' ', '_')}_banner.png"
    banner_path = generate_banner(repository.name, banner_filename)
    banner_generated = True

    await state.update_data(
        enhanced_data=enhanced_data,
        post_text=post_text,
        banner_path=str(banner_path) if banner_path else None,
        banner_generated=banner_generated,
    )
    await state.set_state(PostStates.previewing_post)

    banner_status = "✅ Generated successfully" if banner_generated else "❌ Generation failed"
    preview_header = (
        f"📋 <b>Post Preview</b>\n\n"
        f"<b>Repository:</b> {repository.name}\n"
        f"<b>Author:</b> {repository.owner}\n"
        f"<b>Banner:</b> {banner_status}\n\n"
    )

    if banner_generated and banner_path:
        preview_header += (
            "<i>📸 Preview below shows exactly how your post will appear when published.</i>\n"
            "<i>You can edit content, regenerate everything, or publish to channel.</i>"
        )

        try:
            await send_banner_preview(message, banner_path, post_text, preview_header)
        except Exception:
            await show_text_only_preview(message, preview_header, post_text, repository)
    else:
        await show_text_only_preview(message, preview_header, post_text, repository)


async def show_text_only_preview(
    message: Message, preview_header: str, post_text: str, repository: GitHubRepository
) -> None:
    full_text = (
        f"{preview_header}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{post_text}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        "<i>Text preview ready. You can edit content, regenerate, or publish.</i>"
    )

    try:
        await try_edit_message(message, full_text, create_keyboard(KeyboardType.PREVIEW))
    except TelegramBadRequest:
        await message.answer(full_text, reply_markup=create_keyboard(KeyboardType.PREVIEW))


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH))
async def publish_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if (
        isinstance(callback.message, InaccessibleMessage)
        or not callback.bot
        or not callback.message
    ):
        return

    data = await state.get_data()
    post_text = data.get("post_text")
    enhanced_data = data.get("enhanced_data")
    banner_path = data.get("banner_path")

    if not post_text or not enhanced_data:
        return

    settings = Settings()  # type: ignore

    try:
        repository = enhanced_data.repository

        if banner_path and Path(banner_path).exists():
            banner_input = FSInputFile(banner_path)
        else:
            banner_filename = f"{repository.name.lower().replace(' ', '_')}_banner.png"
            banner_path = generate_banner(repository.name, banner_filename)
            banner_input = FSInputFile(banner_path)

        await callback.bot.send_photo(
            chat_id=settings.channel_id, photo=banner_input, caption=post_text
        )

        cleanup_banner(str(banner_path) if banner_path else None)

        success_text = (
            "✅ <b>Post Published Successfully!</b>\n\n"
            f"Repository: {repository.name}\n"
            f"Author: {repository.owner}\n\n"
            "The post has been sent to the configured channel."
        )

        try:
            await try_edit_message(callback.message, success_text)
        except TelegramBadRequest:
            await callback.message.answer(success_text)

        await callback.answer("Post published to channel successfully!")

    except Exception as e:
        error_text = (
            "❌ <b>Failed to Publish Post</b>\n\n"
            f"Repository: {enhanced_data.repository.name}\n"
            f"Author: {enhanced_data.repository.owner}\n\n"
            f"Error: {e!s}\n\n"
            "Please check the channel ID configuration and bot permissions."
        )

        try:
            await try_edit_message(callback.message, error_text)
        except TelegramBadRequest:
            await callback.message.answer(error_text)

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

    edit_text = (
        f"✏️ <b>Edit Post</b>\n"
        f"Repository: {enhanced_data.repository.name}\n\n"
        f"Select a field to update:\n"
        f"• Description\n"
        f"• Tags\n"
        f"• Features\n"
        f"• Links"
    )

    try:
        await try_edit_message(callback.message, edit_text, create_keyboard(KeyboardType.EDIT))
    except TelegramBadRequest:
        await callback.message.answer(edit_text, reply_markup=create_keyboard(KeyboardType.EDIT))

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

    regenerate_text = (
        "🔄 <b>Regenerating</b>\nClearing cache and generating new content.\n<i>Please wait...</i>"
    )

    try:
        await try_edit_message(callback.message, regenerate_text)
    except TelegramBadRequest:
        await callback.message.answer(regenerate_text)

    await state.set_state(PostStates.waiting_for_confirmation)

    fake_callback_data = PostCallback(action=PostAction.CONFIRM)
    await confirm_post_handler(callback, state, fake_callback_data)


@router.callback_query(PostCallback.filter(F.action == PostAction.BACK_TO_PREVIEW))
async def back_to_preview_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")
    post_text = data.get("post_text")

    if not callback.message or not enhanced_data or not post_text:
        return

    await state.set_state(PostStates.previewing_post)

    try:
        await callback.message.edit_caption(
            caption=post_text, reply_markup=create_keyboard(KeyboardType.PREVIEW)
        )
    except TelegramBadRequest:
        await show_post_preview(callback.message, state, enhanced_data)

    await callback.answer("Returned to preview!")


@router.callback_query(PostCallback.filter(F.action == PostAction.CANCEL))
async def cancel_callback_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    current_state = await state.get_state()
    if current_state:
        data = await state.get_data()
        cleanup_banner(data.get("banner_path"))
        await state.clear()

    cancel_text = (
        "❌ <b>Post Creation Cancelled</b>\n\nYou can start again anytime with /post command."
    )

    try:
        await try_edit_message(callback.message, cancel_text)
    except TelegramBadRequest:
        await callback.message.answer(cancel_text)

    await callback.answer("Post cancelled!")


def create_edit_message(field: EditField, enhanced_data: EnhancedRepositoryData) -> str:
    match field:
        case EditField.DESCRIPTION:
            title = "📝 Edit Description"
            current_value = get_post_description(
                enhanced_data.repository, enhanced_data.ai_content
            )
            current_text = f"<i>{current_value or 'No description available'}</i>"
            tips = [
                "Keep it 2-3 sentences",
                "Focus on user benefits",
                "Explain what the app/tool does",
                "Avoid technical jargon",
            ]
            example = None

        case EditField.TAGS:
            title = "🏷️ Edit Tags"
            current_value = get_post_tags(enhanced_data.repository, enhanced_data.ai_content)
            current_text = (
                " ".join(f"#{tag}" for tag in current_value)
                if current_value
                else "No tags available"
            )
            tips = [
                "Use underscores for multi-word tags (media_player)",
                "5-7 tags maximum",
                "Focus on functionality and category",
                "Avoid generic tags like 'android' or 'app'",
            ]
            example = "media player video audio streaming"

        case EditField.FEATURES:
            title = "⭐ Edit Key Features"
            current_value = (
                enhanced_data.ai_content.key_features if enhanced_data.ai_content else []
            )
            current_text = (
                "\n".join(f"• {f}" for f in current_value)
                if current_value
                else "No features available"
            )
            tips = [
                "3-4 features maximum",
                "Focus on user benefits",
                "Be specific and clear",
                "Highlight unique selling points",
            ]
            example = (
                "Supports all video formats\nCustom playback controls\nOffline viewing capability"
            )

        case EditField.LINKS:
            title = "🔗 Edit Important Links"
            current_value = (
                enhanced_data.ai_content.important_links if enhanced_data.ai_content else []
            )
            current_text = (
                "\n".join(f"• {link['title']}: {link['url']}" for link in current_value)
                if current_value
                else "No additional links available"
            )
            tips = [
                "2-3 links maximum",
                "Include download links",
                "Add documentation if available",
                "Verify all URLs work",
            ]
            example = (
                "Download App: https://play.google.com/store/apps/details?id=com.app\n"
                "Official Website: https://www.example.com\n"
                "User Guide: https://guide.example.com"
            )

    suffix = " in this format:" if field == EditField.LINKS else "."

    parts = [
        f"{title}\n",
        f"<b>Current {field.value.title()}:</b>",
        current_text,
        "",
        f"Send me the new {field.value}{suffix}",
    ]

    if example:
        parts.extend(["", "<b>Example:</b>", example])

    parts.extend(["", "<b>Tips:</b>"] + [f"• {tip}" for tip in tips])

    return "\n".join(parts)


async def handle_field_edit(
    callback: CallbackQuery, field: EditField, enhanced_data: EnhancedRepositoryData
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    edit_text = create_edit_message(field, enhanced_data)
    keyboard = create_keyboard(KeyboardType.BACK_TO_EDIT)

    try:
        await try_edit_message(callback.message, edit_text, keyboard)
    except TelegramBadRequest:
        await callback.message.answer(edit_text, reply_markup=keyboard)


def format_enhanced_post(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> str:
    description = (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description
    )
    tags = (
        ai_content.relevant_tags[:5]
        if ai_content and ai_content.relevant_tags
        else repository.topics[:5]
    )

    parts = [f"<b>{repository.name}</b>"]

    if description:
        parts.append(f"<i>{description}</i>")

    if ai_content and ai_content.key_features:
        features = "\n".join(f"• {feature}" for feature in ai_content.key_features)
        parts.append(f"<b>Key Features:</b>\n{features}")

    links = [f'• <a href="{repository.url}">GitHub Repository</a>']
    if ai_content and ai_content.important_links:
        links.extend([
            f'• <a href="{link["url"]}">{link["title"]}</a>'
            for link in ai_content.important_links[:3]
        ])

    parts.extend([
        "<b>Links:</b>\n" + "\n".join(links),
        f"<b>Author:</b> <code>{repository.owner}</code>",
    ])

    if tags:
        hashtags = " ".join(f"#{tag}" for tag in tags)
        parts.append(f"<b>Tags:</b> {hashtags}")

    parts.append("<b>Follow:</b> @AndroidRepo // <b>Join:</b> @AndroidRepo_chat")
    return "\n\n".join(parts)


def get_post_description(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> str | None:
    return (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description
    )


def get_post_tags(
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
    if (
        isinstance(callback.message, InaccessibleMessage)
        or not callback.message
        or not callback_data.field
    ):
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")
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
        await state.update_data(editing_field=callback_data.field.value)

    match callback_data.field:
        case EditField.DESCRIPTION:
            await handle_field_edit(callback, EditField.DESCRIPTION, enhanced_data)
        case EditField.TAGS:
            await handle_field_edit(callback, EditField.TAGS, enhanced_data)
        case EditField.FEATURES:
            await handle_field_edit(callback, EditField.FEATURES, enhanced_data)
        case EditField.LINKS:
            await handle_field_edit(callback, EditField.LINKS, enhanced_data)

    await callback.answer(f"Edit {callback_data.field.value} mode activated!")


def update_enhanced_data(
    enhanced_data: EnhancedRepositoryData, field: EditField, new_text: str
) -> None:
    match field:
        case EditField.DESCRIPTION:
            update_description(enhanced_data, new_text)
        case EditField.TAGS:
            update_tags(enhanced_data, new_text)
        case EditField.FEATURES:
            update_features(enhanced_data, new_text)
        case EditField.LINKS:
            update_links(enhanced_data, new_text)


def update_description(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    text = new_text.strip()
    if enhanced_data.ai_content:
        enhanced_data.ai_content.enhanced_description = text
    else:
        enhanced_data.repository.description = text


def update_tags(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    tags = [
        tag.strip().lower().replace(" ", "_")
        for tag in re.split(r"[,\s]+", new_text.strip())
        if tag.strip()
    ]

    if enhanced_data.ai_content:
        enhanced_data.ai_content.relevant_tags = tags[:7]
    else:
        enhanced_data.repository.topics = tags[:7]


def update_features(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    features = [
        line.strip().lstrip("•").strip()
        for line in new_text.replace(";", "\n").split("\n")
        if line.strip()
    ]

    if enhanced_data.ai_content:
        enhanced_data.ai_content.key_features = features[:4]


def update_links(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    links = []
    for line in new_text.strip().split("\n"):
        if ":" in line and "http" in line:
            title, url = line.split(":", 1)
            links.append({"title": title.strip(), "url": url.strip(), "type": "custom"})

    if enhanced_data.ai_content:
        enhanced_data.ai_content.important_links = links[:3]


@router.message(
    PostStates.editing_description,
    PostStates.editing_tags,
    PostStates.editing_features,
    PostStates.editing_links,
    F.text,
)
async def handle_field_text_edit(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    current_state = await state.get_state()
    if not current_state:
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")

    if not enhanced_data:
        await message.reply("❌ Edit session expired. Please start over with /post")
        await state.clear()
        return

    match current_state:
        case PostStates.editing_description.state:
            field = EditField.DESCRIPTION
        case PostStates.editing_tags.state:
            field = EditField.TAGS
        case PostStates.editing_features.state:
            field = EditField.FEATURES
        case PostStates.editing_links.state:
            field = EditField.LINKS
        case _:
            return

    try:
        update_enhanced_data(enhanced_data, field, message.text)
        await finalize_field_edit(message, state, enhanced_data, field)
    except Exception:
        await message.reply(
            f"❌ <b>Error updating {field.value.title()}</b>\n"
            "Something went wrong while updating this field. Please try again or /cancel."
        )


@router.message(
    PostStates.editing_description,
    PostStates.editing_tags,
    PostStates.editing_features,
    PostStates.editing_links,
)
async def handle_invalid_field_input(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if not current_state:
        return

    match current_state:
        case PostStates.editing_description.state:
            field = EditField.DESCRIPTION
        case PostStates.editing_tags.state:
            field = EditField.TAGS
        case PostStates.editing_features.state:
            field = EditField.FEATURES
        case PostStates.editing_links.state:
            field = EditField.LINKS
        case _:
            return

    await message.reply(f"❗ Send {field.value} text or /cancel to abort editing.")


async def finalize_field_edit(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData, field: EditField
) -> None:
    data = await state.get_data()
    cleanup_banner(data.get("banner_path"))

    await state.update_data(enhanced_data=enhanced_data)

    new_post_text = format_enhanced_post(enhanced_data.repository, enhanced_data.ai_content)
    await state.update_data(post_text=new_post_text)
    await state.set_state(PostStates.previewing_post)

    await message.reply(
        f"✅ <b>{field.value.title()} updated!</b>\n"
        f"Your changes have been saved. The preview has been updated with your new content.\n\n"
        f"You can continue editing, publish the post, or make further changes.",
        reply_markup=create_keyboard(KeyboardType.PREVIEW),
    )


@router.callback_query(EditCallback.filter(F.action == EditAction.BACK_TO_MENU))
async def back_to_edit_menu_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: EditCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    data = await state.get_data()
    enhanced_data = data.get("enhanced_data")
    if not enhanced_data:
        return

    await edit_post_handler(callback, state, PostCallback(action=PostAction.EDIT))
    await callback.answer("Returned to edit menu!")


async def send_banner_preview(
    message: Message, banner_path: str | Path, post_text: str, preview_header: str
) -> None:
    if message.photo:
        await message.delete()
        await message.answer(preview_header)
        await message.answer_photo(
            photo=FSInputFile(banner_path),
            caption=post_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )
    else:
        await try_edit_message(message, preview_header)
        await message.answer_photo(
            photo=FSInputFile(banner_path),
            caption=post_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )
