# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.modules.posts.callbacks import PostAction, PostCallback
from bot.modules.posts.utils import KeyboardType, PostStates, create_keyboard

router = Router(name="back_to_preview")


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

    await callback.message.edit_caption(
        caption=post_text, reply_markup=create_keyboard(KeyboardType.PREVIEW)
    )

    await callback.answer("Returned to preview")
