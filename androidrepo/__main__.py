# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2023 Hitalo M. <https://github.com/HitaloM>

import asyncio
import sys

import sentry_sdk
from cashews.exceptions import CacheBackendInteractionError

from androidrepo import bot, cache, config, dp, i18n
from androidrepo.handlers import language, pm_menu
from androidrepo.middlewares.acl import ACLMiddleware
from androidrepo.middlewares.i18n import MyI18nMiddleware
from androidrepo.utils.command_list import set_ui_commands
from androidrepo.utils.logging import log


async def main():
    try:
        await cache.ping()
    except (CacheBackendInteractionError, TimeoutError):
        sys.exit(log.critical("Can't connect to RedisDB! Exiting..."))

    if config.sentry_url:
        log.info("Starting sentry.io integraion...")

        sentry_sdk.init(
            config.sentry_url,
            traces_sample_rate=1.0,
        )

    dp.message.middleware(ACLMiddleware())
    dp.message.middleware(MyI18nMiddleware(i18n=i18n))
    dp.callback_query.middleware(ACLMiddleware())
    dp.callback_query.middleware(MyI18nMiddleware(i18n=i18n))

    dp.include_routers(pm_menu.router, language.router)

    await set_ui_commands(bot, i18n)

    useful_updates = dp.resolve_used_update_types()
    await dp.start_polling(bot, allowed_updates=useful_updates)

    await cache.clear()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("AndroidRepo stopped!")
