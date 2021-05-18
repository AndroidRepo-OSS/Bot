# This file is part of AndroidRepo (Telegram Bot)
# Copyright (C) 2021 AmanoTeam

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from typing import List

import httpx
import rapidjson as json
from pyrogram import filters
from pyrogram.types import Message

from androidrepo.handlers.utils.magisk import get_changelog, get_magisk, get_modules

from ..androidrepo import AndroidRepo

TYPES: List[str] = ["beta", "stable", "canary"]


@AndroidRepo.on_message(filters.cmd("magisk"))
async def on_magisk_m(c: AndroidRepo, m: Message):
    command = m.text.split()[0]
    m_type = m.text[len(command) :]

    sm = await m.reply("Checking...")

    if len(m_type) < 1:
        m_type = "stable"
    else:
        m_type = m_type[1:]

    m_type = m_type.lower()

    if m_type not in TYPES:
        await sm.edit(f"The version type '<b>{m_type}</b>' was not found.")
        return

    RAW_URL = "https://github.com/topjohnwu/magisk-files/raw/master"
    async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
        response = await client.get(f"{RAW_URL}/{m_type}.json")
        data = json.loads(response.read())

    magisk = data["magisk"]

    text = f"<b>Type</b>: <code>{m_type}</code>"
    text += f"\n\n<b>Magisk</b>: <a href='{magisk['link']}'>{magisk['versionCode']}</a> ({'v' if magisk['version'][0].isdecimal() else ''}{magisk['version']})"
    text += f"\n<b>Changelog</b>: {await get_changelog(magisk['note'])}"

    keyboard = [[("Full Changelog", magisk["note"], "url")]]

    await sm.edit_text(
        text,
        reply_markup=c.ikb(keyboard),
        disable_web_page_preview=True,
        parse_mode="combined",
    )


@AndroidRepo.on_message(filters.sudo & filters.cmd("modules"))
async def on_modules_m(c: AndroidRepo, m: Message):
    return await get_modules(m)


@AndroidRepo.on_message(filters.sudo & filters.cmd("magisks"))
async def on_magisks_m(c: AndroidRepo, m: Message):
    return await get_magisk(m)
