# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import Router
from aiogram.types import Message

from bot.modules.posts.utils import PostStates

router = Router(name="invalid_repository_url")


@router.message(PostStates.waiting_for_repository_url)
async def invalid_repository_url_handler(message: Message) -> None:
    await message.reply(
        "❌ <b>Invalid Input</b>\n\n"
        "Please send a valid GitHub or GitLab repository URL.\n\n"
        "💡 Use /cancel to abort."
    )
