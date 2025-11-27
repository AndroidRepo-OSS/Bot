# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router, flags
from aiogram.filters import CommandStart
from aiogram.utils.formatting import Bold, Text

if TYPE_CHECKING:
    from aiogram.types import Message

router = Router(name="basic")


@router.message(CommandStart())
@flags.chat_action(initial_sleep=0.0)
async def handle_start(message: Message) -> None:
    user = message.from_user
    display_name = user.full_name if user else "there"
    greeting = Text("Hello, ", Bold(display_name), "!")
    await message.answer(**greeting.as_kwargs())
