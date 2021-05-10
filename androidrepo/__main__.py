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

import logging

from pyrogram import idle
from pyrogram.session import Session
from rich import box
from rich import print as rprint
from rich.logging import RichHandler
from rich.panel import Panel
from tortoise import run_async

from androidrepo.androidrepo import AndroidRepo
from androidrepo.database import connect_database

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
rprint(Panel.fit(header, border_style="white", box=box.ASCII))


# Disable ugly pyrogram notice print
Session.notice_displayed = True


async def main() -> None:
    await connect_database()

    await AndroidRepo().start()
    await idle()


if __name__ == "__main__":
    try:
        run_async(main())
    except KeyboardInterrupt:
        log.warning("Forced stop... Bye!")
        pass
