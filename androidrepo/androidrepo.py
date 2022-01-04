# This file is part of AndroidRepo (Telegram Bot)
# Copyright (C) 2022 AmanoTeam

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import platform
from typing import BinaryIO, List, Union

import aiocron
import pyrogram
import sentry_sdk
from pyrogram import Client
from pyrogram.errors import BadRequest, ChatWriteForbidden, MessageDeleteForbidden
from pyrogram.helpers import ikb
from pyrogram.raw.all import layer
from pyrogram.types import User
from tortoise import Tortoise

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
from androidrepo.database.database import connect_database
from androidrepo.handlers.utils.magisk import check_magisk, check_modules

log = logging.getLogger(__name__)


class AndroidRepo(Client):
    def __init__(self):
        name = self.__class__.__name__.lower()
        self.is_sudo = SUDO_USERS

        super().__init__(
            session_name=name,
            app_version=f"AndroidRepo v{androidrepo.__version__}",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            parse_mode="html",
            workers=24,
            workdir="androidrepo",
            plugins={"root": "androidrepo.handlers"},
            sleep_threshold=180,
        )

    async def start(self):
        await super().start()
        await connect_database()

        # Misc monkeypatch
        self.me = await self.get_me()
        self.ikb = ikb

        if not SENTRY_KEY or SENTRY_KEY == "":
            log.warning("No sentry.io key found! Service not initialized.")
        else:
            log.info("Starting sentry.io service.")
            sentry_sdk.init(SENTRY_KEY, traces_sample_rate=1.0)

        log.info(
            f"AndroidRepo for Pyrogram v{pyrogram.__version__} (Layer {layer}) started on @{self.me.username}. Hi."
        )

        # Startup message
        start_message = (
            f"<b>AndroidRepo <code>v{androidrepo.__version__}</code> started...</b>\n"
            f"- <b>Pyrogram:</b> <code>v{pyrogram.__version__}</code>\n"
            f"- <b>Python:</b> <code>v{platform.python_version()}</code>\n"
            f"- <b>System:</b> <code>{self.system_version}</code>"
        )
        try:
            for user in self.is_sudo:
                await self.send_message(chat_id=user, text=start_message)
        except (BadRequest, ChatWriteForbidden):
            log.warning("Unable to send the startup message to the SUDO_USERS")

        # Sync Magisk every 1h
        @aiocron.crontab("0 * * * *")
        async def magisk_sync() -> None:
            await check_modules(self)
            await check_magisk(self)

    async def stop(self, *args):
        await Tortoise.close_connections()
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
