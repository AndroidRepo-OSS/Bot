"""Android Repository Telegram Bot utilities."""
# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

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
