# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from collections.abc import Iterable

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class ChatFilter(BaseFilter):
    __slots__ = ("_chat_ids",)

    def __init__(self, chat_ids: int | Iterable[int]) -> None:
        if isinstance(chat_ids, Iterable) and not isinstance(chat_ids, (int, str, bytes)):
            self._chat_ids = tuple(int(chat_id) for chat_id in chat_ids)
        else:
            self._chat_ids = (int(chat_ids),)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        chat_id = self._extract_chat_id(event)
        if chat_id is None:
            return False
        return chat_id in self._chat_ids

    @staticmethod
    def _extract_chat_id(event: Message | CallbackQuery) -> int | None:
        if isinstance(event, Message):
            return event.chat.id

        if isinstance(event, CallbackQuery) and event.message is not None:
            return event.message.chat.id

        return None
