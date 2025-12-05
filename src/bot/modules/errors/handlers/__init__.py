# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from aiogram import Router

from . import telegram, unexpected

router = Router(name="errors")
router.include_router(telegram.router)
router.include_router(unexpected.router)

__all__ = ("router", "telegram", "unexpected")
