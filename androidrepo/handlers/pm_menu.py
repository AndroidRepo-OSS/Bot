# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2023 Hitalo M. <https://github.com/HitaloM>

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.i18n import gettext as _

router = Router(name="pm_menu")


@router.message(Command("start"))
async def start(message: Message):
    await message.answer(_("Hello!"))
