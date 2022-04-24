# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from typing import List

from pyrogram import enums, filters
from pyrogram.types import Message

from androidrepo.database import LSPosed
from androidrepo.handlers.utils.xposed import get_lsposed

from ..androidrepo import AndroidRepo

TYPES: List[str] = ["riru", "zygisk"]


@AndroidRepo.on_message(filters.cmd("lsposed"))
async def lsposed(c: AndroidRepo, m: Message):
    command = m.text.split()[0]
    branch = m.text[len(command) :]

    sm = await m.reply("Checking...")

    branch = "zygisk" if len(branch) < 1 else branch[1:]
    branch = branch.lower()

    if branch not in TYPES:
        await sm.edit(f"The version type '<b>{branch}</b>' was not found.")
        return

    _lsposed = await LSPosed.get(branch=branch)

    text = f"<b>{branch.capitalize()} - LSPosed</b>"
    text += f"\n\n<b>Version</b>: <code>{_lsposed.version}</code> (<code>{_lsposed.version_code}</code>)"
    text += f"\n<b>Changelog</b>: {_lsposed.changelog}"

    keyboard = [[("⬇️ Download", _lsposed.link, "url")]]

    await sm.edit_text(
        text,
        reply_markup=c.ikb(keyboard),
        parse_mode=enums.ParseMode.DEFAULT,
        disable_web_page_preview=True,
    )


@AndroidRepo.on_message(filters.sudo & filters.cmd("lsposeds"))
async def lsposeds(c: AndroidRepo, m: Message):
    return await get_lsposed(m)
