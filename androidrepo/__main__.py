# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import logging

from pyrogram.session import Session
from rich import box
from rich import print as rprint
from rich.logging import RichHandler
from rich.panel import Panel

from androidrepo.androidrepo import AndroidRepo
from androidrepo.utils import is_windows

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


# Use uvloop to improve speed if available
try:
    import uvloop

    uvloop.install()
except ImportError:
    if not is_windows():
        log.warning("uvloop is not installed and therefore will be disabled.")


# Beautiful init with rich
header = ":rocket: [bold green]AndroidRepo Running...[/bold green] :rocket:"
rprint(Panel.fit(header, border_style="white", box=box.ASCII))


# Disable ugly pyrogram notice print
Session.notice_displayed = True


if __name__ == "__main__":
    try:
        AndroidRepo().run()
    except KeyboardInterrupt:
        log.warning("Forced stop... Bye!")
