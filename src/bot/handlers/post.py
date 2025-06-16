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
from bot.utils.models import (
    AIGeneratedContent,
    EnhancedRepositoryData,
    GitHubRepository,
    GitLabRepository,
    ImportantLink,
)
from bot.utils.repository_client import RepositoryClient

router = Router(name="post")

REPOSITORY_URL_PATTERN = re.compile(r"^https?://(github\.com|gitlab\.com)/[\w.-]+/[\w.-]+/?$")


class PostStates(StatesGroup):
    waiting_for_repository_url = State()
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


def format_enhanced_post(
    repository: GitHubRepository | GitLabRepository, ai_content: AIGeneratedContent | None
) -> str:
    project_name = get_project_name(repository, ai_content)
    desc = (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description or ""
    )
    tags = (
        ai_content.relevant_tags if ai_content and ai_content.relevant_tags else repository.topics
    )[:5]

    parts = [f"<b>{project_name}</b>"]
    if desc:
        parts.append(f"<i>{desc}</i>")

    features = ai_content.key_features if ai_content and ai_content.key_features else []
    if features:
        parts.append("✨ <b>Key Features:</b>\n" + "\n".join(f"• {f}" for f in features))

    platform_name = "GitHub" if isinstance(repository, GitHubRepository) else "GitLab"
    links_list = (ai_content.important_links if ai_content and ai_content.important_links else [])[
        :3
    ]
    link_items = [f'• <a href="{repository.url}">{platform_name} Repository</a>'] + [
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
    repository: GitHubRepository | GitLabRepository, ai_content: AIGeneratedContent | None
) -> str | None:
    return (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description
    )


def get_post_tags(
    repository: GitHubRepository | GitLabRepository, ai_content: AIGeneratedContent | None
) -> list[str]:
    tags = (
        ai_content.relevant_tags if ai_content and ai_content.relevant_tags else repository.topics
    )
    return tags[:7] if tags else []


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
                "Explain what the app does",
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
                "Use underscores for multi-word tags",
                "Maximum 5-7 tags",
                "Focus on functionality and category",
                "Avoid generic tags",
            ]
            example = "media_player video audio streaming"

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
                "Maximum 3-4 features",
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
                "Maximum 2-3 links",
                "Include download links",
                "Add documentation if available",
                "Verify all URLs work",
            ]
            example = (
                "Download App: https://play.google.com/store/apps/details?id=com.app\n"
                "Official Website: https://www.example.com"
            )

    suffix = " in this format:" if field == EditField.LINKS else "."

    parts = [
        f"{title}\n",
        f"<b>Current {get_field_name(field).title()}:</b>",
        current_text,
        "",
        f"Send the new {get_field_name(field)}{suffix}",
    ]

    if example:
        parts.extend(["", "<b>Example:</b>", example])

    parts.extend(["", "<b>Tips:</b>"] + [f"• {tip}" for tip in tips])

    return "\n".join(parts)


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
        "<b>Examples:</b>\n"
        "<code>https://github.com/user/repository</code>\n"
        "<code>https://gitlab.com/user/repository</code>\n\n"
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
            "Please send a valid repository URL.\n\n"
            "<b>Examples:</b>\n"
            "<code>https://github.com/user/repository</code>\n"
            "<code>https://gitlab.com/user/repository</code>"
        )
        return

    url = message.text.strip()
    if not REPOSITORY_URL_PATTERN.match(url):
        await message.reply(
            "❌ <b>Invalid Repository URL</b>\n\n"
            "Please provide a valid repository URL from GitHub or GitLab.\n\n"
            "<b>Examples:</b>\n"
            "<code>https://github.com/user/repository</code>\n"
            "<code>https://gitlab.com/user/repository</code>\n\n"
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
        "Please send a valid repository URL.\n\n"
        "<b>Examples:</b>\n"
        "<code>https://github.com/user/repository</code>\n"
        "<code>https://gitlab.com/user/repository</code>\n\n"
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
        update_enhanced_data(enhanced_data, editing_field, message.text)
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


async def show_post_preview(
    message: Message, state: FSMContext, enhanced_data: EnhancedRepositoryData
) -> None:
    repository = enhanced_data.repository
    ai_content = enhanced_data.ai_content

    post_text = format_enhanced_post(repository, ai_content)
    banner_buffer = banner_generated = None

    try:
        project_name = get_project_name(repository, ai_content)
        banner_buffer = generate_banner(project_name)
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

    banner_status = "✅ Ready" if banner_generated else "❌ Failed"
    preview_header = (
        f"📋 <b>Post Preview</b>\n\n"
        f"<b>Repository:</b> {repository.name}\n"
        f"<b>Author:</b> {repository.owner}\n"
        f"<b>Banner:</b> {banner_status}\n\n"
    )

    if banner_generated and banner_buffer:
        preview_header += (
            "<i>Preview shows how your post will appear when published.</i>\n"
            "<i>You can edit content, regenerate, or publish to channel.</i>"
        )

        try:
            await send_banner_preview(message, banner_buffer, post_text, preview_header)
        except Exception:
            project_name = get_project_name(repository, ai_content)
            await message.answer(
                "❌ <b>Banner Error</b>\n\n"
                f"Could not generate banner for <b>{project_name}</b>.\n\n"
                "<b>Next steps:</b>\n"
                "• Try /post again to retry\n"
                "• Check repository name validity\n\n"
                "<i>Banner is required for channel publishing.</i>"
            )
            await state.clear()
    else:
        project_name = get_project_name(repository, ai_content)
        await message.answer(
            "❌ <b>Banner Generation Failed</b>\n\n"
            f"Could not create banner for <b>{project_name}</b>.\n\n"
            "<b>Next steps:</b>\n"
            "• Try /post again to retry\n"
            "• Check repository name validity\n\n"
            "<i>Banner is required for channel publishing.</i>"
        )
        await state.clear()


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

    url_parts = repository_url.rstrip("/").split("/")
    owner, repo_name = url_parts[-2], url_parts[-1]

    await try_edit_message(
        callback.message,
        f"🔄 <b>Processing Repository</b>\n\n"
        f"<b>Repository:</b> {repo_name}\n"
        f"<b>Author:</b> {owner}\n\n"
        f"<i>Fetching data and generating content...</i>",
    )

    try:
        settings = Settings()  # type: ignore

        async with RepositoryClient() as client:
            enhanced_data = await client.get_enhanced_repository_data(
                repository_url,
                settings.openai_api_key.get_secret_value(),
                openai_base_url=settings.openai_base_url,
            )

        can_submit, last_submission_date = await can_submit_app(enhanced_data.repository.id)

        if not can_submit and last_submission_date:
            if last_submission_date.tzinfo is None:
                last_submission_date = last_submission_date.replace(tzinfo=UTC)

            days_since_last = (datetime.now(tz=UTC) - last_submission_date).days
            remaining_days = 90 - days_since_last

            await try_edit_message(
                callback.message,
                f"🚫 <b>Repost Not Allowed</b>\n\n"
                f"<b>Repository:</b> {repo_name}\n"
                f"<b>Author:</b> {owner}\n\n"
                f"This app was posted <b>{days_since_last} days ago</b>.\n"
                f"Please wait <b>{remaining_days} more days</b> to repost.\n\n"
                f"<i>3-month policy prevents channel spam.</i>",
            )
            await state.clear()
            return

        await show_post_preview(callback.message, state, enhanced_data)

    except Exception as e:
        await try_edit_message(
            callback.message,
            f"❌ <b>Processing Failed</b>\n\n"
            f"<b>Repository:</b> <code>{repository_url}</code>\n\n"
            f"<b>Error:</b> <code>{str(e)[:200]}...</code>\n\n"
            f"💡 Please try again with /post",
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
            "❌ <b>Banner Required</b>\n\n"
            "Cannot publish without a banner.\n\n"
            "💡 Try regenerating the post to create a new banner."
        )
        await try_edit_message(callback.message, error_text)
        return

    settings = Settings()  # type: ignore

    try:
        repository = enhanced_data.repository
        project_name = get_project_name(repository, enhanced_data.ai_content)
        banner_input = BufferedInputFile(
            banner_buffer.getvalue(),
            filename=f"{project_name.lower().replace(' ', '_')}_banner.png",
        )

        sent_message = await callback.bot.send_photo(
            chat_id=settings.channel_id, photo=banner_input, caption=post_text
        )

        await submit_app(repository, sent_message.message_id)

        banner_buffer.close()

        success_text = (
            "✅ <b>Post Published Successfully!</b>\n\n"
            f"<b>Project:</b> {project_name}\n"
            f"<b>Repository:</b> {repository.name}\n"
            f"<b>Author:</b> {repository.owner}\n\n"
            "<i>Post sent to channel and saved to database.</i>"
        )
        await try_edit_message(callback.message, success_text)

    except Exception as e:
        project_name = get_project_name(enhanced_data.repository, enhanced_data.ai_content)
        error_text = (
            "❌ <b>Publishing Failed</b>\n\n"
            f"<b>Project:</b> {project_name}\n"
            f"<b>Repository:</b> {enhanced_data.repository.name}\n"
            f"<b>Author:</b> {enhanced_data.repository.owner}\n\n"
            f"<b>Error:</b> {e!s}\n\n"
            "<i>Check channel ID and bot permissions.</i>"
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

    project_name = get_project_name(enhanced_data.repository, enhanced_data.ai_content)
    edit_text = (
        f"✏️ <b>Edit Post</b>\n\n"
        f"<b>Project:</b> {project_name}\n"
        f"<b>Repository:</b> {enhanced_data.repository.name}\n\n"
        f"<b>Select field to update:</b>\n"
        f"• Description\n"
        f"• Tags\n"
        f"• Features\n"
        f"• Links"
    )

    await try_edit_message(callback.message, edit_text, create_keyboard(KeyboardType.EDIT))
    await callback.answer("Edit mode activated")


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE))
async def regenerate_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    repository_url = (await state.get_data()).get("repository_url")

    if not callback.message or not repository_url:
        return

    repository_cache.delete(repository_url)

    regenerate_text = (
        "🔄 <b>Regenerating Content</b>\n\n"
        "Clearing cache and generating new content.\n\n"
        "<i>Please wait...</i>"
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

    await try_edit_message(callback.message, cancel_text)
    await callback.answer("Post cancelled")


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
        await callback.answer(f"Edit {get_field_name(callback_data.field)} mode activated")


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


async def handle_field_edit(
    callback: CallbackQuery, field: EditField, enhanced_data: EnhancedRepositoryData
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    edit_text = create_edit_message(field, enhanced_data)
    keyboard = create_keyboard(KeyboardType.BACK_TO_EDIT)

    await try_edit_message(callback.message, edit_text, keyboard)


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
        f"✅ <b>{get_field_name(field).title()} Updated!</b>\n\n"
        f"Your changes have been saved.\n"
        f"The preview has been updated with your new content.\n\n"
        f"💡 You can continue editing, publish, or make further changes."
    )


def get_project_name(
    repository: GitHubRepository | GitLabRepository, ai_content: AIGeneratedContent | None
) -> str:
    return ai_content.project_name if ai_content and ai_content.project_name else repository.name
