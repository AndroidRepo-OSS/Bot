# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import contextlib

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


async def try_edit_message(
    message: Message, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=markup)
            return
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        with contextlib.suppress(TelegramBadRequest):
            await message.answer(text, reply_markup=markup)
