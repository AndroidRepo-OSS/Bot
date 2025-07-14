# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import asyncio
import logging

import uvloop
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import settings
from .database import database
from .handlers.posts import router as posts_router
from .handlers.updater import router as updater_router
from .utils.logger import LogLevel, get_logger

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%d-%m-%Y %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    async with database:
        defaults = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
        bot = Bot(token=settings.bot_token.get_secret_value(), default=defaults)

        async with bot:
            logger.info("Starting the bot...")

            dp.include_routers(updater_router, posts_router)

            bot_logger = get_logger(bot)
            await bot_logger.log_system_event(
                event_description="Bot successfully initialized and ready to operate",
                level=LogLevel.SUCCESS,
                extra_data={
                    "bot_id": settings.bot_id,
                    "database_status": "connected",
                    "routers_loaded": ["updater", "posts", "logs"],
                },
            )

            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
            runner.run(main())
    except KeyboardInterrupt:
        logger.info("Forced stop... Bye!")
