# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings
from bot.filters.sudo import SudoersFilter
from bot.utils.logger import LogLevel, get_logger, log_system_event, log_user_action

router = Router(name="logs")
router.message.filter(
    F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]),
    F.chat.id == settings.group_id,
    SudoersFilter(),
)


@router.message(Command("test_logs"))
async def test_logs_command(message: Message) -> None:
    if not message.bot or not message.from_user:
        return

    logger = get_logger(message.bot)

    if not logger.enabled:
        await message.reply(
            "❌ <b>Logging System Disabled</b>\n\n"
            "Configure <code>GROUP_ID</code> and <code>LOGS_TOPIC_ID</code> in the "
            "configuration file to enable the logging system."
        )
        return

    await log_user_action(
        bot=message.bot,
        user=message.from_user,
        action_description="Tested the logging system",
        level=LogLevel.INFO,
        extra_data={"command": "/test_logs"},
    )

    await log_system_event(
        bot=message.bot,
        event_description="Logging system tested via administrative command",
        level=LogLevel.SUCCESS,
        extra_data={"triggered_by": message.from_user.full_name or "Unknown"},
    )

    await message.reply(
        "✅ <b>Logging System Tested</b>\n\nCheck the 'Logs' topic to see the test messages sent."
    )


@router.message(Command("logs_status"))
async def logs_status_command(message: Message) -> None:
    if not message.bot:
        return

    logger = get_logger(message.bot)

    status_emoji = "✅" if logger.enabled else "❌"
    status_text = "Enabled" if logger.enabled else "Disabled"

    config_info = [
        f"<b>Status:</b> {status_emoji} {status_text}",
        f"<b>Group ID:</b> <code>{settings.group_id}</code>",
        f"<b>Logs Topic ID:</b> <code>{settings.logs_topic_id}</code>",
    ]

    if logger.enabled:
        config_info.append(
            f"<b>Target:</b> Group {settings.group_id}, Topic {settings.logs_topic_id}"
        )
    else:
        config_info.append(
            "<b>Required Action:</b> Configure GROUP_ID and LOGS_TOPIC_ID to enable"
        )

    await message.reply("📊 <b>Logging System Status</b>\n\n" + "\n".join(config_info))
