# This file is part of AndroidRepo (Telegram Bot)
# Copyright (C) 2021 AmanoTeam

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

import asyncio
import logging
import platform
from typing import BinaryIO, List, Union

import aioschedule as schedule
import pyrogram
import pyromod
from pyrogram import Client
from pyrogram.errors import BadRequest, MessageDeleteForbidden
from pyrogram.raw.all import layer
from pyrogram.types import User
from pyromod.helpers import ikb

import androidrepo
from androidrepo.config import (
    API_HASH,
    API_ID,
    BOT_TOKEN,
    CHANNEL_ID,
    STAFF_ID,
    SUDO_USERS,
)
from androidrepo.handlers.utils.magisk import check_modules
from androidrepo.utils import filters, modules

log = logging.getLogger(__name__)


class AndroidRepo(Client):
    def __init__(self):
        name = self.__class__.__name__.lower()

        super().__init__(
            session_name=name,
            app_version=f"AndroidRepo v{androidrepo.__version__}",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            parse_mode="html",
            workers=24,
            sleep_threshold=180,
        )

    async def start(self):
        await super().start()

        # Misc monkeypatch
        self.me = await self.get_me()
        self.is_sudo = SUDO_USERS
        self.ikb = ikb

        log.info(
            f"AndroidRepo for Pyrogram v{pyrogram.__version__} (Layer {layer}) started on @{self.me.username}. Hi."
        )

        # Built-in modules and filters system
        filters.load(self)
        modules.load(self)

        # Startup message
        start_message = (
            f"<b>AndroidRepo <code>v{androidrepo.__version__}</code> started...</b>\n"
            f"- <b>Pyrogram:</b> <code>v{pyrogram.__version__}</code>\n"
            f"- <b>Pyromod:</b> <code>v{pyromod.__version__}</code>\n"
            f"- <b>Python:</b> <code>v{platform.python_version()}</code>\n"
            f"- <b>System:</b> <code>{self.system_version}</code>"
        )
        try:
            for user in self.is_sudo:
                await self.send_message(chat_id=user, text=start_message)
        except BadRequest:
            log.warning("Unable to send the startup message to the SUDO_USERS")
            pass

        await check_modules(self)
        schedule.every(1).hours.do(check_modules, c=self)

        while True:
            await schedule.run_pending()
            await asyncio.sleep(0.1)

    async def stop(self, *args):
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
