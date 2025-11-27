# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from collections.abc import Iterable

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class TopicFilter(BaseFilter):
    __slots__ = ("_topic_ids",)

    def __init__(self, topic_ids: int | Iterable[int] | None) -> None:
        if topic_ids is None:
            self._topic_ids: tuple[int, ...] | None = None
        elif isinstance(topic_ids, Iterable) and not isinstance(topic_ids, (int, str, bytes)):
            self._topic_ids = tuple(int(topic_id) for topic_id in topic_ids)
        else:
            self._topic_ids = (int(topic_ids),)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if self._topic_ids is None:
            return True

        thread_id = self._extract_thread_id(event)
        if thread_id is None:
            return False

        return thread_id in self._topic_ids

    @staticmethod
    def _extract_thread_id(event: Message | CallbackQuery) -> int | None:
        if isinstance(event, Message):
            return event.message_thread_id

        if isinstance(event, CallbackQuery):
            message = event.message
            if isinstance(message, Message):
                return message.message_thread_id

        return None
