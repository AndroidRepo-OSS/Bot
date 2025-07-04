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
from .scheduler import PostScheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%d-%m-%Y %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    await database.create_tables()
    logger.info("Database initialized")

    defaults = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
    bot = Bot(token=settings.bot_token.get_secret_value(), default=defaults)

    scheduler = PostScheduler(bot, settings)
    await scheduler.start()
    logger.info("Post scheduler started")

    dp.include_routers(posts_router)

    logger.info("Starting bot...")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await scheduler.stop()
        await bot.session.close()
        await database.close()
        logger.info("Database connection closed")


if __name__ == "__main__":
    try:
        with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
            runner.run(main())
    except KeyboardInterrupt:
        logger.info("Forced stop... Bye!")
