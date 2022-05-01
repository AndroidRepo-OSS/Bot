# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import logging
import platform
from typing import BinaryIO, List, Union

import aiocron
import pyrogram
import sentry_sdk
from pyrogram import Client, enums
from pyrogram.errors import BadRequest, ChatWriteForbidden, MessageDeleteForbidden
from pyrogram.helpers import ikb
from pyrogram.raw.all import layer
from pyrogram.types import User

import androidrepo
from androidrepo.config import (
    API_HASH,
    API_ID,
    BOT_TOKEN,
    CHANNEL_ID,
    SENTRY_KEY,
    STAFF_ID,
    SUDO_USERS,
)
from androidrepo.utils import shell_exec

log = logging.getLogger(__name__)


class AndroidRepo(Client):
    def __init__(self):
        name = self.__class__.__name__.lower()

        super().__init__(
            name=name,
            app_version=f"AndroidRepo v{androidrepo.__version__}",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            parse_mode=enums.ParseMode.HTML,
            workers=24,
            workdir="androidrepo",
            plugins={"root": "androidrepo.modules"},
            sleep_threshold=180,
        )

    async def start(self):
        await super().start()

        # Save version info
        self.version_code = int((await shell_exec("git rev-list --count HEAD"))[0])
        self.version = str((await shell_exec("git rev-parse --short HEAD"))[0])

        # Misc monkeypatch
        self.me = await self.get_me()
        self.ikb = ikb
        self.is_sudo = SUDO_USERS

        if not SENTRY_KEY or SENTRY_KEY == "":
            log.warning("No sentry.io key found! Service not initialized.")
        else:
            log.info("Starting sentry.io service.")
            sentry_sdk.init(SENTRY_KEY, traces_sample_rate=1.0)

        log.info(
            f"AndroidRepo for Pyrogram v{pyrogram.__version__} (Layer {layer}) started on @{self.me.username}. Hi."
        )

        # Startup message
        try:
            for user in self.is_sudo:
                await self.send_message(
                    chat_id=user,
                    text=(
                        f"<b>AndroidRepo</b> <a href='https://github.com/AmanoTeam/AndroidRepo/commit/{self.version}'>{self.version}</a> (<code>{self.version_code}</code>) started!\n"
                        f"- <b>Pyrogram:</b> <code>v{pyrogram.__version__}</code>\n"
                        f"- <b>Python:</b> <code>v{platform.python_version()}</code>\n"
                        f"- <b>System:</b> <code>{self.system_version}</code>"
                    ),
                    disable_web_page_preview=True,
                )
        except (BadRequest, ChatWriteForbidden):
            log.warning("Unable to send the startup message to the SUDO_USERS")

        # Sync Magisk every 1h
        async def magisk_sync() -> None:
            from androidrepo.modules.utils.magisk import check_magisk, check_modules
            from androidrepo.modules.utils.quickpic import check_quickpic
            from androidrepo.modules.utils.xposed import check_lsposed

            await check_modules(self)
            await check_lsposed(self)
            await check_quickpic(self)
            await check_magisk(self)

        aiocron.crontab("0 * * * *", func=magisk_sync, args=(self,), start=True)

    async def stop(self):
        await super().stop()
        log.info("AndroidRepo stopped... Bye.")

    async def send_log_message(self, chat_id: int, text: str, *args, **kwargs):
        return await self.send_message(chat_id=chat_id, text=text, *args, **kwargs)

    async def delete_log_messages(
        self, message_ids: Union[int, List[int]], *args, **kwargs
    ):
        try:
            await self.delete_messages(
                chat_id=STAFF_ID, message_ids=message_ids, *args, **kwargs
            )
        except (MessageDeleteForbidden, BadRequest):
            return
        return

    async def send_channel_document(
        self, document: Union[str, BinaryIO], *args, **kwargs
    ):
        return await self.send_document(
            chat_id=CHANNEL_ID, document=document, *args, **kwargs
        )

    def is_sudoer(self, user: User) -> bool:
        return user.id in self.is_sudo
