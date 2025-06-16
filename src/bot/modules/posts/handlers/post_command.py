# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.modules.posts.utils import PostStates

router = Router(name="post_command")


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
