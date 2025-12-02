# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest

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
    def _format_timestamp() -> str:
        now_utc = datetime.now(UTC)
        now_brasilia = now_utc.astimezone(ZoneInfo("America/Sao_Paulo"))

        utc_str = now_utc.strftime("%d/%m/%Y %H:%M:%S")
        brasilia_str = now_brasilia.strftime("%d/%m/%Y %H:%M:%S")

        return f"<b>UTC:</b> {utc_str}\n<b>Brasília:</b> {brasilia_str}"

    @staticmethod
    def _format_user(user: User) -> str:
        name = user.full_name
        username = f"@{user.username}" if user.username else f"ID: {user.id}"
        return f"{name} ({username})"

    async def _send_log(self, message: str) -> None:
        with suppress(TelegramBadRequest):
            await self._bot.send_message(
                chat_id=self._chat_id, message_thread_id=self._topic_id, text=message, disable_notification=True
            )

    async def log_bot_started(self) -> None:
        timestamp = self._format_timestamp()
        message = f"🤖 <b>Bot Started</b>\n\n{timestamp}"
        await self._send_log(message)

    async def log_post_started(self, user: User, repository: RepositoryInfo) -> None:
        timestamp = self._format_timestamp()
        user_info = self._format_user(user)

        message = (
            f"📝 <b>Post Started</b>\n\n"
            f"<b>User:</b> {user_info}\n"
            f"<b>Project:</b> <code>{repository.full_name}</code>\n"
            f"<b>URL:</b> {repository.web_url}\n"
            f"<b>Platform:</b> {repository.platform.value.title()}\n\n"
            f"{timestamp}"
        )
        await self._send_log(message)

    async def log_post_published(self, user: User, repository: RepositoryInfo) -> None:
        timestamp = self._format_timestamp()
        user_info = self._format_user(user)

        message = (
            f"✅ <b>Post Published</b>\n\n"
            f"<b>User:</b> {user_info}\n"
            f"<b>Project:</b> <code>{repository.full_name}</code>\n"
            f"<b>URL:</b> {repository.web_url}\n"
            f"<b>Platform:</b> {repository.platform.value.title()}\n\n"
            f"{timestamp}"
        )
        await self._send_log(message)

    async def log_post_cancelled(self, user: User, repository: RepositoryInfo) -> None:
        timestamp = self._format_timestamp()
        user_info = self._format_user(user)

        message = (
            f"❌ <b>Post Cancelled</b>\n\n"
            f"<b>User:</b> {user_info}\n"
            f"<b>Project:</b> <code>{repository.full_name}</code>\n"
            f"<b>URL:</b> {repository.web_url}\n\n"
            f"{timestamp}"
        )
        await self._send_log(message)

    async def log_post_edited(self, user: User, repository: RepositoryInfo, edit_request: str) -> None:
        timestamp = self._format_timestamp()
        user_info = self._format_user(user)

        truncated_request = edit_request[:200] + "..." if len(edit_request) > 200 else edit_request

        message = (
            f"✏️ <b>Post Edited</b>\n\n"
            f"<b>User:</b> {user_info}\n"
            f"<b>Project:</b> <code>{repository.full_name}</code>\n"
            f"<b>Edit Request:</b> {truncated_request}\n\n"
            f"{timestamp}"
        )
        await self._send_log(message)
