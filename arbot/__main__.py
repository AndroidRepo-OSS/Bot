# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2023 Hitalo M. <https://github.com/HitaloM>

import asyncio
import sys
from contextlib import suppress

import sentry_sdk
from aiogram import __version__ as aiogram_version
from aiogram.exceptions import TelegramForbiddenError
from aiosqlite import __version__ as aiosqlite_version
from cashews.exceptions import CacheBackendInteractionError
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from arbot import __version__ as arbot_version
from arbot import bot, cache, config, dp, i18n
from arbot.database.base import create_tables
from arbot.handlers import load_modules
from arbot.middlewares.acl import ACLMiddleware
from arbot.middlewares.i18n import MyI18nMiddleware
from arbot.utils.command_list import set_ui_commands
from arbot.utils.logging import log


async def main():
    try:
        await cache.ping()
    except (CacheBackendInteractionError, TimeoutError):
        sys.exit(log.critical("Can't connect to RedisDB! Exiting..."))

    await create_tables()

    if config.sentry_url:
        log.info("Starting sentry.io integraion.")

        sentry_sdk.init(
            str(config.sentry_url),
            traces_sample_rate=1.0,
            integrations=[RedisIntegration(), AioHttpIntegration()],
        )

    dp.message.middleware(ACLMiddleware())
    dp.message.middleware(MyI18nMiddleware(i18n=i18n))
    dp.callback_query.middleware(ACLMiddleware())
    dp.callback_query.middleware(MyI18nMiddleware(i18n=i18n))

    load_modules(dp)

    await set_ui_commands(bot, i18n)

    with suppress(TelegramForbiddenError):
        if config.logs_channel:
            log.info("Sending startup notification.")
            await bot.send_message(
                config.logs_channel,
                text=(
                    "<b>Gojira is up and running!</b>\n\n"
                    f"<b>Version:</b> <code>{arbot_version}</code>\n"
                    f"<b>AIOgram version:</b> <code>{aiogram_version}</code>\n"
                    f"<b>AIOSQLite version:</b> <code>{aiosqlite_version}</code>"
                ),
            )

    # resolve used update types
    useful_updates = dp.resolve_used_update_types()
    await dp.start_polling(bot, allowed_updates=useful_updates)

    # clear cashews cache
    log.info("Clearing cashews cache.")
    await cache.clear()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("AndroidRepo[Bot] stopped!")