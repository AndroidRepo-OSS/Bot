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

import httpx
import rapidjson as json

from pyrogram import Client, filters
from pyrogram.types import Message

from bot.handlers.utils.magisk import get_modules

TYPES = ["beta", "stable", "canary"]


@Client.on_message(filters.cmd("magisk"))
async def on_magisk_m(c: Client, m: Message):
    command = m.text.split()[0]
    type = m.text[len(command) :]

    sm = await m.reply("Checking...")

    if len(type) < 1:
        type = "stable"
    else:
        type = type[1:]

    type = type.lower()

    if type not in TYPES:
        return await sm.edit(f"The version type <b>{type}</b> was not found.")

    if type == "canary":
        RAW_URL = "https://github.com/topjohnwu/magisk_files/raw/canary"
    else:
        RAW_URL = "https://github.com/topjohnwu/magisk_files/raw/master"

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{RAW_URL}/{type}.json")
        data = json.loads(response.read())

    app = data["app"]
    magisk = data["magisk"]

    text = f"<b>Type</b>: <code>{type}</code>"
    if type == "canary":
        text += f"\n\n<b>Magisk</b>: <a href='https://raw.githubusercontent.com/topjohnwu/magisk_files/canary/app-debug.apk'>{app['versionCode']}</a> (v{app['version']})"
        text += f"\n<b>Changelog</b>: {await get_changelog('https://github.com/topjohnwu/magisk_files/raw/canary/notes.md')}"
    elif type == "stable":
        text += f"<b>\n\nMagisk</b>: <a href='{magisk['link']}'>{magisk['versionCode']}</a> (v{magisk['version']})"
        text += f"<b>\nChangelog</b>: {await get_changelog('https://github.com/topjohnwu/Magisk/raw/master/docs/changes.md')}"
    elif type == "beta":
        text += f"<b>\n\nMagisk</b>: <a href='{magisk['link']}'>{magisk['versionCode']}</a> (v{magisk['version']})"
        text += f"<b>\nChangelog</b>: {await get_changelog(magisk['note'])}"
    text += f"\n\n<a href='{data['uninstaller']['link']}'>Uninstaller</a>"

    await sm.edit_text(text, disable_web_page_preview=True, parse_mode="combined")


async def get_changelog(url: str) -> str:
    changelog = ""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.read()
        lines = data.decode().split("\n")
        latest_version = False
        for line in lines:
            if len(line) < 1:
                continue
            if line.startswith("##"):
                if not latest_version:
                    latest_version = True
                else:
                    break
            else:
                changelog += f"\n    {line}"
    return changelog


@Client.on_message(filters.sudo & filters.cmd("modules"))
async def on_modules_m(c: Client, m: Message):
    return await get_modules(m)
