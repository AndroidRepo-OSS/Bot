# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import contextlib
import re
from datetime import UTC, datetime
from enum import Enum
from io import BytesIO

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.database import can_submit_app, submit_app
from bot.utils.banner_generator import generate_banner
from bot.utils.cache import repository_cache
from bot.utils.github_client import GitHubClient
from bot.utils.models import (
    AIGeneratedContent,
    EnhancedRepositoryData,
    GitHubRepository,
    ImportantLink,
)

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


def get_field_name(field: EditField) -> str:
    """Convert EditField enum to human-readable string."""
    field_names = {
        EditField.DESCRIPTION: "description",
        EditField.TAGS: "tags",
        EditField.FEATURES: "features",
        EditField.LINKS: "links",
    }
    return field_names.get(field, "unknown")


def create_keyboard(keyboard_type: KeyboardType) -> InlineKeyboardMarkup:
    buttons = {
        KeyboardType.CONFIRMATION: [
            ("✅ Confirm", PostCallback(action=PostAction.CONFIRM)),
            ("❌ Cancel", PostCallback(action=PostAction.CANCEL)),
        ],
        KeyboardType.PREVIEW: [
            ("✅ Publish", PostCallback(action=PostAction.PUBLISH)),
            ("✏️ Edit", PostCallback(action=PostAction.EDIT)),
            ("🔄 Regenerate", PostCallback(action=PostAction.REGENERATE)),
            ("❌ Cancel", PostCallback(action=PostAction.CANCEL)),
        ],
        KeyboardType.EDIT: [
            ("📝 Description", EditCallback(action=EditAction.FIELD, field=EditField.DESCRIPTION)),
            ("🏷️ Tags", EditCallback(action=EditAction.FIELD, field=EditField.TAGS)),
            ("⭐ Features", EditCallback(action=EditAction.FIELD, field=EditField.FEATURES)),
            ("🔗 Links", EditCallback(action=EditAction.FIELD, field=EditField.LINKS)),
            ("🔙 Back", PostCallback(action=PostAction.BACK_TO_PREVIEW)),
            ("❌ Cancel", PostCallback(action=PostAction.CANCEL)),
        ],
        KeyboardType.BACK_TO_EDIT: [
            ("🔙 Back", EditCallback(action=EditAction.BACK_TO_MENU)),
        ],
    }

    adjustments = {
        KeyboardType.CONFIRMATION: (2,),
        KeyboardType.PREVIEW: (2, 2),
        KeyboardType.EDIT: (2, 2, 2),
        KeyboardType.BACK_TO_EDIT: (1,),
    }

    builder = InlineKeyboardBuilder()
    for text, data in buttons[keyboard_type]:
        builder.button(text=text, callback_data=data)
    builder.adjust(*adjustments[keyboard_type])
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
        with contextlib.suppress(TelegramBadRequest):
            await message.answer(text, reply_markup=markup)


@router.message(Command("post"))
async def post_command_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    banner_buffer = data.get("banner_buffer")
    if banner_buffer:
        banner_buffer.close()

    await state.clear()
    await state.set_state(PostStates.waiting_for_github_url)

    await message.reply(
        "📱 <b>Repository Post Creator</b>\n"
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

    if banner_buffer := (await state.get_data()).get("banner_buffer"):
        banner_buffer.close()

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

    url_parts = github_url.rstrip("/").split("/")
    owner, repo_name = url_parts[-2], url_parts[-1]
    repository_full_name = f"{owner}/{repo_name}"

    await try_edit_message(
        callback.message,
        f"🔄 <b>Processing Repository</b>\n\n"
        f"<b>Repository:</b> {repository_full_name}\n"
        f"<i>Fetching repository data and generating enhanced content...</i>",
    )

    try:
        settings = Settings()  # type: ignore

        async with GitHubClient() as client:
            enhanced_data = await client.get_enhanced_repository_data(
                github_url,
                settings.openai_api_key.get_secret_value(),
                settings.openai_base_url,
            )

        can_submit, last_submission_date = await can_submit_app(enhanced_data.repository.id)

        if not can_submit and last_submission_date:
            if last_submission_date.tzinfo is None:
                last_submission_date = last_submission_date.replace(tzinfo=UTC)

            days_since_last = (datetime.now(tz=UTC) - last_submission_date).days
            remaining_days = 90 - days_since_last

            await try_edit_message(
                callback.message,
                f"🚫 <b>Repost Prevention</b>\n\n"
                f"<b>Repository:</b> {repository_full_name}\n\n"
                f"❌ This app was already posted <b>{days_since_last} days ago</b>\n"
                f"You need to wait <b>{remaining_days} more days</b> before reposting.\n\n"
                f"<i>Our 3-month repost policy prevents channel spam.</i>",
            )
            await state.clear()
            return

        await show_post_preview(callback.message, state, enhanced_data)

    except Exception as e:
        await try_edit_message(
            callback.message,
            f"❌ <b>Error Processing Repository</b>\n\n"
            f"<code>{github_url}</code>\n\n"
            f"<b>Error:</b> <code>{str(e)[:200]}...</code>",
        )
        await state.clear()


async def show_post_preview(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData
) -> None:
    repository = enhanced_data.repository
    ai_content = enhanced_data.ai_content

    post_text = format_enhanced_post(repository, ai_content)
    banner_buffer = banner_generated = None

    try:
        banner_buffer = generate_banner(repository.name)
        banner_generated = True
    except Exception:
        banner_generated = False

    await state.update_data(
        enhanced_data=enhanced_data,
        post_text=post_text,
        banner_buffer=banner_buffer,
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

    if banner_generated and banner_buffer:
        preview_header += (
            "<i>📸 Preview below shows exactly how your post will appear when published.</i>\n"
            "<i>You can edit content, regenerate everything, or publish to channel.</i>"
        )

        try:
            await send_banner_preview(message, banner_buffer, post_text, preview_header)
        except Exception:
            await message.answer(
                "❌ <b>Banner Error</b>\n\n"
                f"Could not generate or display banner for {repository.name}.\n"
                "This is required to publish to the channel.\n\n"
                "Please try:\n"
                "• Use /post again to retry\n"
                "• Check if the repository name is valid"
            )
            await state.clear()
    else:
        await message.answer(
            "❌ <b>Banner Generation Failed</b>\n\n"
            f"Could not generate banner for {repository.name}.\n"
            "A banner is required to publish to the channel.\n\n"
            "Please try:\n"
            "• Use /post again to retry\n"
            "• Check if the repository name is valid"
        )
        await state.clear()


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
    post_text, enhanced_data, banner_buffer = (
        data.get("post_text"),
        data.get("enhanced_data"),
        data.get("banner_buffer"),
    )

    if not post_text or not enhanced_data:
        return

    if not banner_buffer:
        error_text = (
            "❌ <b>No Banner Available</b>\n\n"
            "Cannot publish post without a banner.\n"
            "Please regenerate the post to create a new banner."
        )
        await try_edit_message(callback.message, error_text)
        return

    settings = Settings()  # type: ignore

    try:
        repository = enhanced_data.repository
        banner_input = BufferedInputFile(
            banner_buffer.getvalue(),
            filename=f"{repository.name.lower().replace(' ', '_')}_banner.png",
        )

        sent_message = await callback.bot.send_photo(
            chat_id=settings.channel_id, photo=banner_input, caption=post_text
        )

        await submit_app(repository, sent_message.message_id)

        banner_buffer.close()

        success_text = (
            "✅ <b>Post Published Successfully!</b>\n\n"
            f"<b>Repository:</b> {repository.name}\n"
            f"<b>Author:</b> {repository.owner}\n\n"
            "<i>The post has been sent to the configured channel and saved to database.</i>"
        )
        await try_edit_message(callback.message, success_text)

    except Exception as e:
        error_text = (
            "❌ <b>Failed to Publish Post</b>\n\n"
            f"Repository: {enhanced_data.repository.name}\n"
            f"Author: {enhanced_data.repository.owner}\n\n"
            f"Error: {e!s}\n\n"
            "Please check the channel ID configuration and bot permissions."
        )
        await try_edit_message(callback.message, error_text)

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

    await try_edit_message(callback.message, edit_text, create_keyboard(KeyboardType.EDIT))
    await callback.answer("Edit mode activated!")


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE))
async def regenerate_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    github_url = (await state.get_data()).get("github_url")

    if not callback.message or not github_url:
        return

    repository_cache.delete(github_url)

    regenerate_text = (
        "🔄 <b>Regenerating</b>\nClearing cache and generating new content.\n<i>Please wait...</i>"
    )

    await try_edit_message(callback.message, regenerate_text)

    await state.set_state(PostStates.waiting_for_confirmation)
    await confirm_post_handler(callback, state, PostCallback(action=PostAction.CONFIRM))


@router.callback_query(PostCallback.filter(F.action == PostAction.BACK_TO_PREVIEW))
async def back_to_preview_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    enhanced_data, post_text = data.get("enhanced_data"), data.get("post_text")

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

    if await state.get_state():
        if banner_buffer := (await state.get_data()).get("banner_buffer"):
            banner_buffer.close()
        await state.clear()

    cancel_text = (
        "❌ <b>Post Creation Cancelled</b>\n\nYou can start again anytime with /post command."
    )

    await try_edit_message(callback.message, cancel_text)
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
                "\n".join(f"• {link.title}: {link.url}" for link in current_value)
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
        f"<b>Current {get_field_name(field).title()}:</b>",
        current_text,
        "",
        f"Send me the new {get_field_name(field)}{suffix}",
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

    await try_edit_message(callback.message, edit_text, keyboard)


def format_enhanced_post(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> str:
    desc = (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description or ""
    )
    tags = (
        ai_content.relevant_tags if ai_content and ai_content.relevant_tags else repository.topics
    )[:5]

    parts = [f"<b>{repository.name}</b>"]
    if desc:
        parts.append(f"<i>{desc}</i>")

    features = ai_content.key_features if ai_content and ai_content.key_features else []
    if features:
        parts.append("✨ <b>Key Features:</b>\n" + "\n".join(f"• {f}" for f in features))

    links_list = (ai_content.important_links if ai_content and ai_content.important_links else [])[
        :3
    ]
    link_items = [f'• <a href="{repository.url}">GitHub Repository</a>'] + [
        f'• <a href="{link.url}">{link.title}</a>' for link in links_list
    ]
    parts.append("🔗 <b>Links:</b>\n" + "\n".join(link_items))

    hashtags = " ".join(f"#{t}" for t in tags)
    author_lines = [f"👤 <b>Author:</b> <code>{repository.owner}</code>"]
    if hashtags:
        author_lines.append(f"🏷️ <b>Tags:</b> {hashtags}")

    parts.append("\n".join(author_lines))
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
    tags = (
        ai_content.relevant_tags if ai_content and ai_content.relevant_tags else repository.topics
    )
    return tags[:7] if tags else []


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
        await handle_field_edit(callback, callback_data.field, enhanced_data)
        await callback.answer(f"Edit {get_field_name(callback_data.field)} mode activated!")


def update_enhanced_data(  # noqa: C901
    enhanced_data: EnhancedRepositoryData, field: EditField, new_text: str
) -> None:
    match field:
        case EditField.DESCRIPTION:
            text = new_text.strip()
            if enhanced_data.ai_content:
                enhanced_data.ai_content.enhanced_description = text
            else:
                enhanced_data.repository.description = text

        case EditField.TAGS:
            tags = [
                tag.strip().lower().replace(" ", "_")
                for tag in re.split(r"[,\s]+", new_text.strip())
                if tag.strip()
            ]

            if enhanced_data.ai_content:
                enhanced_data.ai_content.relevant_tags = tags[:7]
            else:
                enhanced_data.repository.topics = tags[:7]

        case EditField.FEATURES:
            features = [
                line.strip().lstrip("•").strip()
                for line in new_text.replace(";", "\n").split("\n")
                if line.strip()
            ]

            if enhanced_data.ai_content:
                enhanced_data.ai_content.key_features = features[:4]

        case EditField.LINKS:
            links = []
            for line in new_text.strip().split("\n"):
                if ":" in line and "http" in line:
                    title, url = line.split(":", 1)
                    links.append(
                        ImportantLink(title=title.strip(), url=url.strip(), type="website")
                    )

            if enhanced_data.ai_content:
                enhanced_data.ai_content.important_links = links[:3]


@router.message(PostStates.editing_description, F.text)
@router.message(PostStates.editing_tags, F.text)
@router.message(PostStates.editing_features, F.text)
@router.message(PostStates.editing_links, F.text)
async def handle_edit_state_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❗ Send the new value or /cancel to abort editing.")
        return

    data = await state.get_data()
    enhanced_data, editing_field_str = data.get("enhanced_data"), data.get("editing_field")

    if not enhanced_data or not editing_field_str:
        await message.reply("❌ Edit session expired. Please start over with /post")
        await state.clear()
        return

    try:
        editing_field = EditField(editing_field_str)
        update_enhanced_data(enhanced_data, editing_field, message.text)
        await finalize_field_edit(message, state, enhanced_data, editing_field)
    except ValueError:
        await message.reply(
            "❌ <b>Invalid field for editing</b>\n"
            "An internal error occurred. Please try again or /cancel."
        )
    except Exception:
        await message.reply(
            f"❌ <b>Error updating {editing_field_str.title()}</b>\n"
            "Something went wrong while updating this field. Please try again or /cancel."
        )


async def finalize_field_edit(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData, field: EditField
) -> None:
    if banner_buffer := (await state.get_data()).get("banner_buffer"):
        banner_buffer.close()

    await state.update_data(enhanced_data=enhanced_data)
    new_post_text = format_enhanced_post(enhanced_data.repository, enhanced_data.ai_content)
    await state.update_data(post_text=new_post_text)
    await state.set_state(PostStates.previewing_post)

    await message.reply(
        f"✅ <b>{get_field_name(field).title()} updated!</b>\n"
        f"Your changes have been saved. The preview has been updated with your new content.\n\n"
        f"You can continue editing, publish the post, or make further changes."
    )


@router.callback_query(EditCallback.filter(F.action == EditAction.BACK_TO_MENU))
async def back_to_edit_menu_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: EditCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    if not (await state.get_data()).get("enhanced_data"):
        return

    await edit_post_handler(callback, state, PostCallback(action=PostAction.EDIT))
    await callback.answer("Returned to edit menu!")


async def send_banner_preview(
    message: Message, banner_buffer: BytesIO, post_text: str, preview_header: str
) -> None:
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
        await try_edit_message(message, preview_header)
        await message.answer_photo(
            photo=banner_input,
            caption=post_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )
