# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.modules.posts.callbacks import PostAction, PostCallback
from bot.modules.posts.handlers.confirm_post import confirm_post_handler
from bot.modules.posts.utils import PostStates, try_edit_message

router = Router(name="regenerate_post")


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE))
async def regenerate_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    repository_url = (await state.get_data()).get("repository_url")

    if not repository_url:
        return

    regenerate_text = "🔄 <b>Regenerating Content</b>\n\n<i>Please wait...</i>"

    await try_edit_message(callback.message, regenerate_text)

    await state.set_state(PostStates.waiting_for_confirmation)
    await confirm_post_handler(callback, state, PostCallback(action=PostAction.CONFIRM))
