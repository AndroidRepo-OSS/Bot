# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from .handlers import telegram, unexpected

if TYPE_CHECKING:
    from aiogram import Dispatcher


def setup_errors(dp: Dispatcher) -> None:
    dp.include_routers(telegram.router, unexpected.router)


__all__ = ("setup_errors",)
