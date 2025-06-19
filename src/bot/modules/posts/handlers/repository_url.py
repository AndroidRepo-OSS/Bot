# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.modules.posts.utils import (
    REPOSITORY_URL_PATTERN,
    KeyboardType,
    PostStates,
    create_keyboard,
)

router = Router(name="repository_url")


@router.message(PostStates.waiting_for_repository_url, F.text)
async def repository_url_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply(
            "❌ <b>Invalid Input</b>\n\n"
            "Please provide a valid repository URL from GitHub or GitLab.\n\n"
        )
        return

    url = message.text.strip()
    if not REPOSITORY_URL_PATTERN.match(url):
        await message.reply(
            "❌ <b>Invalid Repository URL</b>\n\n"
            "Please provide a valid repository URL from GitHub or GitLab.\n\n"
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
