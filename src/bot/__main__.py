# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import argparse
import asyncio
import logging

import uvloop
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import LinkPreviewOptions

from .config import BotSettings
from .container import create_dispatcher
from .logging import get_logger, setup_logging

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AndroidRepo Bot")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


async def main() -> None:
    settings = BotSettings()  # ty: ignore[missing-argument]

    defaults = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview=LinkPreviewOptions(is_disabled=True))
    bot = Bot(token=settings.bot_token, default=defaults)

    dp = create_dispatcher(bot=bot, settings=settings)

    await logger.ainfo("Starting bot...")
    allowed_updates = dp.resolve_used_update_types()
    await dp.start_polling(bot, allowed_updates=allowed_updates)


if __name__ == "__main__":
    args = parse_args()
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level=log_level)
    with asyncio.Runner(debug=args.debug, loop_factory=uvloop.new_event_loop) as runner:
        runner.run(main())
