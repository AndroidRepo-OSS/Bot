# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class TopicFilter(BaseFilter):
    __slots__ = ("_topic_id",)

    def __init__(self, topic_id: int) -> None:
        self._topic_id = int(topic_id)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        thread_id = self._extract_thread_id(event)
        if thread_id is None:
            return False
        return thread_id == self._topic_id

    @staticmethod
    def _extract_thread_id(event: Message | CallbackQuery) -> int | None:
        if isinstance(event, Message):
            return event.message_thread_id

        if isinstance(event, CallbackQuery):
            message = event.message
            if isinstance(message, Message):
                return message.message_thread_id

        return None
