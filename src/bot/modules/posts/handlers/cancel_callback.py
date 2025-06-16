# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.modules.posts.callbacks import PostAction, PostCallback
from bot.modules.posts.utils import try_edit_message

router = Router(name="cancel_callback")


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
