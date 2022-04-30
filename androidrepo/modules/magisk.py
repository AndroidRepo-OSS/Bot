# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from typing import List

import httpx
from pyrogram import enums, filters
from pyrogram.types import Message

from androidrepo.database.magisk import create_magisk, get_magisk_by_branch
from androidrepo.modules.utils import get_changelog
from androidrepo.modules.utils.magisk import get_magisk, get_modules

from ..androidrepo import AndroidRepo

TYPES: List[str] = ["beta", "stable", "canary"]


@AndroidRepo.on_message(filters.cmd("magisk"))
async def on_magisk_m(c: AndroidRepo, m: Message):
    command = m.text.split()[0]
    m_type = m.text[len(command) :]

    sm = await m.reply("Checking...")

    m_type = "stable" if len(m_type) < 1 else m_type[1:]
    m_type = m_type.lower()

    if m_type not in TYPES:
        await sm.edit(f"The version type '<b>{m_type}</b>' was not found.")
        return

    _magisk = await get_magisk_by_branch(branch=m_type)
    if _magisk is None:
        async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
            r = await client.get(
                f"https://github.com/topjohnwu/magisk-files/raw/master/{m_type}.json"
            )
            data = r.json()
            await client.aclose()
        magisk = data["magisk"]
        changelog = await get_changelog(magisk["note"])
        await create_magisk(
            branch=m_type,
            version=magisk["version"],
            version_code=magisk["versionCode"],
            link=magisk["link"],
            note=magisk["note"],
            changelog=changelog,
        )
        _magisk = await get_magisk_by_branch(branch=m_type)

    text = f"<b>Magisk Branch</b>: <code>{m_type}</code>"
    text += f"\n\n<b>Version</b>: <a href='{_magisk['link']}'>{'v' if _magisk['version'].isdecimal() else ''}{_magisk['version']}</a> ({_magisk['version_code']})"
    text += f"\n<b>Changelog</b>: {_magisk['changelog']}"

    keyboard = [[("Full Changelog", _magisk["note"], "url")]]

    await sm.edit_text(
        text,
        reply_markup=c.ikb(keyboard),
        parse_mode=enums.ParseMode.DEFAULT,
        disable_web_page_preview=True,
    )


@AndroidRepo.on_message(filters.sudo & filters.cmd("modules"))
async def on_modules_m(c: AndroidRepo, m: Message):
    return await get_modules(m)


@AndroidRepo.on_message(filters.sudo & filters.cmd("magisks"))
async def on_magisks_m(c: AndroidRepo, m: Message):
    return await get_magisk(m)
