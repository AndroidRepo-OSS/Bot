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
import re
from typing import BinaryIO, List, Union

import aioschedule as schedule
import pyrogram
import pyromod
from pyrogram import Client, filters, idle
from pyrogram.session import Session
from rich import box, print
from rich.logging import RichHandler
from rich.panel import Panel
from tortoise import run_async

import androidrepo
from androidrepo.config import (
    API_HASH,
    API_ID,
    BOT_TOKEN,
    CHANNEL_ID,
    PREFIXES,
    STAFF_ID,
    SUDO_USERS,
)
from androidrepo.database import connect_database
from androidrepo.handlers.utils.magisk import check_modules
from androidrepo.utils import filters, modules

# Logging colorized by rich
FORMAT = "%(message)s"
logging.basicConfig(
    level="INFO",
    format=FORMAT,
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)


# To avoid some pyrogram annoying log
logging.getLogger("pyrogram.syncer").setLevel(logging.WARNING)
logging.getLogger("pyrogram.client").setLevel(logging.WARNING)
logging.getLogger("aiodown").setLevel(logging.WARNING)

log = logging.getLogger("rich")


# Beautiful init with rich
header = ":rocket: [bold green]AndroidRepo Running...[/bold green] :rocket:"
print(Panel.fit(header, border_style="white", box=box.ASCII))

bot = Client(
    "bot",
    API_ID,
    API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode="html",
)


# Disable ugly pyrogram notice print
Session.notice_displayed = True


# Monkeypatch
async def send_log_message(text: str, *args, **kwargs):
    return await bot.send_message(chat_id=STAFF_ID, text=text, *args, **kwargs)


async def delete_log_messages(message_ids: Union[int, List[int]], *args, **kwargs):
    try:
        await bot.delete_messages(
            chat_id=STAFF_ID, message_ids=message_ids, *args, **kwargs
        )
    except BaseException:
        return
    return


async def send_channel_document(document: Union[str, BinaryIO], *args, **kwargs):
    return await bot.send_document(
        chat_id=CHANNEL_ID, document=document, *args, **kwargs
    )


# Main
async def main():
    bot.send_log_message = send_log_message
    bot.delete_log_messages = delete_log_messages
    bot.send_channel_document = send_channel_document

    # Start bot and connect to db
    await connect_database()
    await bot.start()

    # Monkeypatch
    bot.me = await bot.get_me()

    # Built-in modules and filters system
    filters.load(bot)
    modules.load(bot)

    startup_message = f"""<b>AndroidRepo</b> <code>v{androidrepo.__version__}</code> <b>started...</b>
- <b>Pyrogram:</b> <code>v{pyrogram.__version__}</code>
- <b>Pyromod:</b> <code>v{pyromod.__version__}</code>
- <b>Python:</b> <code>v{platform.python_version()}</code>
- <b>System:</b> <code>{bot.system_version}</code>
           """
    for sudo_user in SUDO_USERS:
        try:
            await bot.send_message(chat_id=sudo_user, text=startup_message)
        except BaseException:
            await bot.send_log_message(
                text=f"Error sending the startup message to <code>{sudo_user}</code>."
            )

    await check_modules(bot)
    schedule.every(1).hours.do(check_modules, c=bot)

    while True:
        await schedule.run_pending()
        await asyncio.sleep(0.1)

    # Idle the bot
    await idle()


if __name__ == "__main__":
    run_async(main())
