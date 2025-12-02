# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import argparse
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AndroidRepo Bot")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


async def main() -> None:
    settings = BotSettings()  # ty: ignore[missing-argument]

    defaults = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
    bot = Bot(token=settings.bot_token, default=defaults)

    dp = Dispatcher(storage=MemoryStorage())
    setup_dependencies(dp, settings=settings)
    register_all(dp, allowed_chat_id=settings.allowed_chat_id, post_topic_id=settings.post_topic_id)

    await logger.ainfo("Starting bot...")
    allowed_updates = dp.resolve_used_update_types()
    await dp.start_polling(bot, allowed_updates=allowed_updates)


if __name__ == "__main__":
    args = parse_args()
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level=log_level)
    anyio.run(main, backend="asyncio", backend_options={"use_uvloop": True})
