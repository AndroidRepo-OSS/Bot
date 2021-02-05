# This file is part of AndroidRepo (Telegram Bot)

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

RAW_URL = "https://github.com/topjohnwu/magisk_files/raw/master"
TYPES = ["beta", "stable"]


@Client.on_message(filters.cmd("magisk"))
async def on_magisk_m(c: Client, m: Message):
    command = m.text.split()[0]
    type = m.text[len(command):]
    
    sm = await m.reply("Checking...")
    
    if len(type) < 1:
        type = "stable"
    else:
        type = type[1:]
        
    if not type in TYPES:
        return await m.reply(f"O tipo de versão <b>{type}</b> não foi encontrado.")
        
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{RAW_URL}/{type}.json")
        data = json.loads(response.read())
        
    app = data["app"]
    magisk = data["magisk"]
    
    text = f"""
<b>Type</b>: <code>{type}</code>

<b>Manager</b>: <a href="{app['link']}">{app['versionCode']}</a> (v{app['version']})
<b>Changelog</b>: {await get_changelog(app['note'])}

<b>Magisk</b>: <a href="{magisk['link']}">{magisk['versionCode']}</a> (v{magisk['version']})
<b>Changelog</b>: {await get_changelog(magisk['note'])}

<a href="{data['uninstaller']['link']}">Uninstaller</a>
    """
    await sm.edit_text(text, disable_web_page_preview=True, parse_mode="combined")
    
async def get_changelog(url: str) -> str:
    changelog = ''
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.read()
        lines = data.decode().split("\n")
        print(lines)
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