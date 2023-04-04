"""Android Repository Telegram Bot utilities."""
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2021-2023 Hitalo M. <https://github.com/HitaloM>

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
