# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from aiogram import Router

from . import command, debug, edit, publish

post_router = Router(name="post")
post_router.include_router(command.router)
post_router.include_router(edit.router)
post_router.include_router(publish.router)

__all__ = ("command", "debug", "edit", "post_router", "publish")
