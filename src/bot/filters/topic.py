# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram.filters import BaseFilter
from aiogram.types import Message


class TopicFilter(BaseFilter):
    def __init__(self, topic_id: int | None = None, topic_name: str | None = None):
        self.topic_id = topic_id
        self.topic_name = topic_name

    async def __call__(self, message: Message) -> bool:
        if not message.chat or not hasattr(message.chat, "is_forum") or not message.chat.is_forum:
            return False

        if self.topic_id is not None:
            return message.message_thread_id == self.topic_id

        if (
            self.topic_name is not None
            and message.reply_to_message
            and message.reply_to_message.forum_topic_created
        ):
            return message.reply_to_message.forum_topic_created.name == self.topic_name

        return False


class SubmissionTopicFilter(TopicFilter):
    def __init__(self):
        super().__init__(topic_name="Submissions")


class LogsTopicFilter(TopicFilter):
    def __init__(self):
        super().__init__(topic_name="Logs")
