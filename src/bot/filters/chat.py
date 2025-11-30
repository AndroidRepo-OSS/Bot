# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class ChatFilter(BaseFilter):
    __slots__ = ("_chat_id",)

    def __init__(self, chat_id: int) -> None:
        self._chat_id = int(chat_id)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        chat_id = self._extract_chat_id(event)
        if chat_id is None:
            return False
        return chat_id == self._chat_id

    @staticmethod
    def _extract_chat_id(event: Message | CallbackQuery) -> int | None:
        if isinstance(event, Message):
            return event.chat.id

        if isinstance(event, CallbackQuery) and event.message is not None:
            return event.message.chat.id

        return None
