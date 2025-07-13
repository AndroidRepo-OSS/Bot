# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import User

from bot.config import settings


class LogLevel(Enum):
    INFO = "ℹ️"
    WARNING = "⚠️"
    ERROR = "❌"
    SUCCESS = "✅"
    DEBUG = "🐛"


class LogAction(Enum):
    POST_CREATED = "post_created"
    POST_UPDATED = "post_updated"
    POST_DELETED = "post_deleted"
    USER_ACTION = "user_action"
    SYSTEM_EVENT = "system_event"
    ERROR_OCCURRED = "error_occurred"


class LoggerSystem:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.group_id = settings.group_id
        self.logs_topic_id = settings.logs_topic_id
        self._enabled = self.group_id != 0 and self.logs_topic_id != 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def log(
        self,
        level: LogLevel,
        action: LogAction,
        message: str,
        user: User | None = None,
        extra_data: dict[str, Any] | None = None,
        silent: bool = False,
    ) -> bool:
        if not self.enabled:
            return False

        try:
            formatted_message = self._format_log_message(level, action, message, user, extra_data)

            await self.bot.send_message(
                chat_id=self.group_id,
                text=formatted_message,
                message_thread_id=self.logs_topic_id,
                parse_mode="HTML",
                disable_notification=silent,
            )
            return True

        except TelegramAPIError as e:
            print(f"Failed to send log message: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error in logging system: {e}")
            return False

    @staticmethod
    def _format_log_message(
        level: LogLevel,
        action: LogAction,
        message: str,
        user: User | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> str:
        timestamp = datetime.now(UTC).strftime("%H:%M:%S")
        action_name = action.value.replace("_", " ").title()

        lines = [f"{level.value} <b>{action_name}</b> - {timestamp}"]

        if user:
            user_info = f"@{user.username}" if user.username else f"ID: {user.id}"
            full_name = user.full_name or "Unknown User"
            lines.append(f"<b>User:</b> {full_name} ({user_info})")

        lines.append(message)

        if extra_data:
            for key, value in extra_data.items():
                if key != "repository":
                    lines.append(f"<b>{key.title()}:</b> {value}")

        return "\n".join(lines)

    async def log_post_action(
        self,
        action: LogAction,
        admin_user: User,
        repository_name: str,
        repository_url: str,
        channel_message_id: int | None = None,
        silent: bool = True,
    ) -> bool:
        extra_data = {}

        if channel_message_id:
            extra_data["message_id"] = str(channel_message_id)

        if action == LogAction.POST_CREATED:
            message = f'New post: <a href="{repository_url}">{repository_name}</a>'
            level = LogLevel.SUCCESS
        elif action == LogAction.POST_UPDATED:
            message = f'Updated: <a href="{repository_url}">{repository_name}</a>'
            level = LogLevel.INFO
        elif action == LogAction.POST_DELETED:
            message = f'Deleted: <a href="{repository_url}">{repository_name}</a>'
            level = LogLevel.WARNING
        else:
            message = f'Action on: <a href="{repository_url}">{repository_name}</a>'
            level = LogLevel.INFO

        return await self.log(
            level=level,
            action=action,
            message=message,
            user=admin_user,
            extra_data=extra_data or None,
            silent=silent,
        )

    async def log_user_action(
        self,
        user: User,
        action_description: str,
        level: LogLevel = LogLevel.INFO,
        extra_data: dict[str, Any] | None = None,
        silent: bool = True,
    ) -> bool:
        return await self.log(
            level=level,
            action=LogAction.USER_ACTION,
            message=action_description,
            user=user,
            extra_data=extra_data,
            silent=silent,
        )

    async def log_system_event(
        self,
        event_description: str,
        level: LogLevel = LogLevel.INFO,
        extra_data: dict[str, Any] | None = None,
        silent: bool = True,
    ) -> bool:
        return await self.log(
            level=level,
            action=LogAction.SYSTEM_EVENT,
            message=event_description,
            extra_data=extra_data,
            silent=silent,
        )

    async def log_error(
        self,
        error_description: str,
        user: User | None = None,
        extra_data: dict[str, Any] | None = None,
        silent: bool = False,
    ) -> bool:
        return await self.log(
            level=LogLevel.ERROR,
            action=LogAction.ERROR_OCCURRED,
            message=error_description,
            user=user,
            extra_data=extra_data,
            silent=silent,
        )


class _LoggerManager:
    def __init__(self):
        self._instance: LoggerSystem | None = None

    def get_logger(self, bot: Bot) -> LoggerSystem:
        if self._instance is None or self._instance.bot != bot:
            self._instance = LoggerSystem(bot)
        return self._instance


_logger_manager = _LoggerManager()


def get_logger(bot: Bot) -> LoggerSystem:
    return _logger_manager.get_logger(bot)
