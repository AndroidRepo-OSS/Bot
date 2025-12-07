# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.formatting import Bold, Text, TextLink, as_key_value, as_list

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import User

    from bot.integrations.repositories import RepositoryInfo


class TelegramLogger:
    __slots__ = ("_bot", "_chat_id", "_topic_id")

    def __init__(self, bot: Bot, chat_id: int, topic_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._topic_id = topic_id

    @staticmethod
    def _truncate(text: str, length: int = 200) -> str:
        return text[:length] + "..." if len(text) > length else text

    @staticmethod
    def _format_datetime(dt: datetime) -> Text:
        aware = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        utc_str = aware.astimezone(UTC).strftime("%d/%m/%Y %H:%M:%S")
        brasilia_str = aware.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
        return as_list(as_key_value("UTC", utc_str), as_key_value("Brasília", brasilia_str))

    @classmethod
    def _format_timestamp(cls) -> Text:
        return cls._format_datetime(datetime.now(UTC))

    @staticmethod
    def _format_user(user: User | None) -> Text | str:
        if not user:
            return "Unknown user"
        name = user.full_name
        username = f"@{user.username}" if user.username else f"ID: {user.id}"
        return Text(name, " (", username, ")")

    @staticmethod
    def _format_project_link(repository: RepositoryInfo) -> TextLink:
        return TextLink(repository.full_name, url=str(repository.web_url))

    def _build_message(
        self, header: Text, user_info: Text | str | None = None, repository: RepositoryInfo | None = None, *extras: Text
    ) -> Text:
        parts = [header]
        details = []

        if user_info:
            details.append(as_key_value("User", user_info))

        if repository:
            details.append(as_key_value("Project", self._format_project_link(repository)))

        if extras:
            details.extend(extras)

        if details:
            parts.append(as_list(*details))

        parts.append(self._format_timestamp())
        return as_list(*parts, sep="\n\n")

    async def _send_log(self, message: Text) -> None:
        with suppress(TelegramBadRequest):
            text, entities = message.render()
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=self._topic_id,
                text=text,
                entities=entities,
                disable_notification=True,
                parse_mode=None,
            )

    async def log_bot_started(self) -> None:
        await self._send_log(self._build_message(Text("🤖 ", Bold("Bot Started"))))

    async def log_post_started(self, user: User, repository: RepositoryInfo) -> None:
        await self._send_log(
            self._build_message(Text("📝 ", Bold("Post Started")), self._format_user(user), repository)
        )

    async def log_post_published(self, user: User, repository: RepositoryInfo) -> None:
        await self._send_log(
            self._build_message(Text("✅ ", Bold("Post Published")), self._format_user(user), repository)
        )

    async def log_post_cancelled(self, user: User, repository: RepositoryInfo) -> None:
        await self._send_log(
            self._build_message(Text("❌ ", Bold("Post Cancelled")), self._format_user(user), repository)
        )

    async def log_post_edited(self, user: User, repository: RepositoryInfo, edit_request: str) -> None:
        await self._send_log(
            self._build_message(
                Text("✏️ ", Bold("Post Edited")),
                self._format_user(user),
                repository,
                as_key_value("Edit Request", self._truncate(edit_request)),
            )
        )

    async def log_post_rejected(self, user: User, repository: RepositoryInfo, reason: str) -> None:
        await self._send_log(
            self._build_message(
                Text("🚫 ", Bold("Post Rejected (Non-Android)")),
                self._format_user(user),
                repository,
                as_key_value("Reason", self._truncate(reason)),
            )
        )

    async def log_post_recently_posted(
        self,
        user: User | None,
        repository: RepositoryInfo,
        *,
        last_posted_at: datetime,
        next_allowed_at: datetime,
        channel_message_id: int,
        channel_link: str,
    ) -> None:
        await self._send_log(
            self._build_message(
                Text("⏳ ", Bold("Post Blocked (recent)")),
                self._format_user(user),
                repository,
                Text(Bold("Last posted:"), "\n", self._format_datetime(last_posted_at)),
                Text(Bold("Next allowed:"), "\n", self._format_datetime(next_allowed_at)),
                as_key_value("Channel message", TextLink(f"#{channel_message_id}", url=channel_link)),
            )
        )
