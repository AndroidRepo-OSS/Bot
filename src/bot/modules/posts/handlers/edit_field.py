# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.modules.posts.callbacks import EditAction, EditCallback, EditField
from bot.modules.posts.utils import (
    KeyboardType,
    PostStates,
    create_keyboard,
    get_field_name,
    get_post_description,
    get_post_tags,
    try_edit_message,
)
from bot.utils.models import EnhancedRepositoryData

router = Router(name="edit_field")


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


async def handle_field_edit(callback, field, enhanced_data) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    edit_text = create_edit_message(field, enhanced_data)
    keyboard = create_keyboard(KeyboardType.BACK_TO_EDIT)

    await try_edit_message(callback.message, edit_text, keyboard)
