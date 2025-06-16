# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.modules.posts.callbacks import PostAction, PostCallback
from bot.modules.posts.utils import (
    KeyboardType,
    PostStates,
    create_keyboard,
    get_project_name,
    try_edit_message,
)

router = Router(name="edit_post")


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
