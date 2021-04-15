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

import os


# Clean terminal
os.system("clear")


# Update requirements
import sys

DGRAY = 'echo -e "\033[1;30m"'
RESET = 'echo -e "\033[0m"'

if "--no-update" not in sys.argv:
    print("\033[0;32mUpdating requirements...\033[0m")
    os.system(f"{DGRAY}; {sys.executable} -m pip install . -U; {RESET}")
    os.system("clear")

print("\033[0m")


# Clean terminal
os.system("clear")


# Start logger
import logging
from rich import box, print
from rich.logging import RichHandler
from rich.panel import Panel


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
text = ":rocket: [bold green]AndroidRepo Running...[/bold green] :rocket:"
print(Panel.fit(text, border_style="white", box=box.ASCII))


# Bot
from pyrogram import Client, filters, idle
from pyrogram.session import Session
from tortoise import run_async
from .config import (
    API_HASH,
    API_ID,
    BOT_TOKEN,
    CHANNEL_ID,
    PREFIXES,
    STAFF_ID,
    SUDO_USERS,
)
from .database import connect_database

bot = Client(
    "bot",
    API_ID,
    API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode="html",
    plugins=dict(root="androidrepo/handlers"),
)


# Disable ugly pyrogram notice print
Session.notice_displayed = True


# Filters
async def sudo_filter(_, __, m):
    user = m.from_user
    if not user:
        return
    return user.id in SUDO_USERS or (user.username and user.username in SUDO_USERS)


import re


def cmd_filter(command: str, *args, **kwargs):
    prefix = f"[{re.escape(''.join(PREFIXES))}]"
    return filters.regex("^" + prefix + command, *args, **kwargs)


filters.sudo = filters.create(sudo_filter, "SudoFilter")
filters.cmd = cmd_filter


# Monkeypatch
async def send_log_message(text: str, *args, **kwargs):
    return await bot.send_message(chat_id=STAFF_ID, text=text, *args, **kwargs)


from typing import BinaryIO, List, Union


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

    # Connect database
    await connect_database()

    # Start bot
    await bot.start()
    bot.me = await bot.get_me()

    # Send startup message
    import pyrogram
    import pyromod
    import platform

    startup_message = f"""<b>AndroidRepo Started...</b>
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

    # Check magisk modules
    from .handlers.utils.magisk import check_modules

    import aioschedule as schedule
    import asyncio

    await check_modules(bot)
    schedule.every(1).hours.do(check_modules, c=bot)

    while True:
        await schedule.run_pending()
        await asyncio.sleep(0.1)

    # Idle the bot
    await idle()


if __name__ == "__main__":
    run_async(main())
