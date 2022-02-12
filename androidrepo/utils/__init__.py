"""Android Repository Telegram Bot utilities."""
# SPDX-License-Identifier: GPLv3
# Copyright (c) 2021-2022 Amano Team

import os
import platform
import sys
from typing import List

import httpx

from . import filters

__all__: List[str] = ["filters"]
httpx_timeout = httpx.Timeout(40, pool=None)


def is_windows() -> bool:
    return bool(
        platform.system().lower() == "windows"
        or os.name == "nt"
        or sys.platform.startswith("win")
    )
