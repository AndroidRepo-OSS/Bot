# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging

import anyio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import BotSettings
from .container import setup_dependencies
from .handlers import register_all
from .logging import get_logger, setup_logging

logger = get_logger(__name__)


async def main() -> None:
    settings = BotSettings()  # pyright: ignore[reportCallIssue]

    defaults = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
    bot = Bot(token=settings.bot_token, default=defaults)

    dp = Dispatcher(storage=MemoryStorage())
    setup_dependencies(dp, settings=settings)
    register_all(dp, allowed_chat_id=settings.allowed_chat_id, post_topic_id=settings.post_topic_id)

    await logger.ainfo("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    setup_logging(level=logging.INFO)
    try:
        anyio.run(main, backend="asyncio", backend_options={"use_uvloop": True})
    except KeyboardInterrupt:
        logger.info("Bot stopped!")
