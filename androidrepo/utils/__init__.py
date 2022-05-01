"""Android Repository Telegram Bot utilities."""
# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import asyncio
import os
import platform
import sys
from typing import List

from . import filters

__all__: List[str] = ["filters"]


def is_windows() -> bool:
    return bool(
        platform.system().lower() == "windows"
        or os.name == "nt"
        or sys.platform.startswith("win")
    )


async def shell_exec(code: str, treat=True) -> str:
    process = await asyncio.create_subprocess_shell(
        code, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )

    stdout = (await process.communicate())[0]
    if treat:
        stdout = stdout.decode().strip()
    return stdout, process
