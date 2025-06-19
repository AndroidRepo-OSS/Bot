# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.modules.posts.callbacks import EditAction, EditCallback, PostAction, PostCallback
from bot.modules.posts.utils import KeyboardType, PostStates, create_keyboard, try_edit_message

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

    edit_text = (
        "✏️ <b>Edit Post</b>\n\n"
        "<b>Select field to update:</b>\n"
        "• Description\n"
        "• Tags\n"
        "• Features\n"
        "• Links"
    )

    await try_edit_message(callback.message, edit_text, create_keyboard(KeyboardType.EDIT))
    await callback.answer("Edit mode activated")


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
