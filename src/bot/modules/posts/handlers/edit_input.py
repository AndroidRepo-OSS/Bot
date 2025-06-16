# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.modules.posts.callbacks import EditField
from bot.modules.posts.utils import PostStates, format_enhanced_post, get_field_name
from bot.utils.models import EnhancedRepositoryData, ImportantLink

router = Router(name="edit_state_input")


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


async def finalize_field_edit(message, state, enhanced_data, field) -> None:
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


def update_enhanced_data(
    enhanced_data: EnhancedRepositoryData, field: EditField, new_text: str
) -> None:
    match field:
        case EditField.DESCRIPTION:
            _update_description(enhanced_data, new_text)
        case EditField.TAGS:
            _update_tags(enhanced_data, new_text)
        case EditField.FEATURES:
            _update_features(enhanced_data, new_text)
        case EditField.LINKS:
            _update_links(enhanced_data, new_text)


def _update_description(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    text = new_text.strip()
    if enhanced_data.ai_content:
        enhanced_data.ai_content.enhanced_description = text
    else:
        enhanced_data.repository.description = text


def _update_tags(enhanced_data: EnhancedRepositoryData, new_text: str) -> None:
    tags = [
        tag.strip().lower().replace(" ", "_")
        for tag in re.split(r"[,\s]+", new_text.strip())
        if tag.strip()
    ]

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
            links.append(ImportantLink(title=title.strip(), url=url.strip(), type="website"))

    if enhanced_data.ai_content:
        enhanced_data.ai_content.important_links = links[:3]
