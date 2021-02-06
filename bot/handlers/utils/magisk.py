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

import asyncio
import datetime
import io
import httpx
import os
import rapidjson as json

from pyrogram import Client
from pyrogram.types import Message
from ...database import Modules
from ... import config
from typing import Dict


RAW_URL = "https://github.com/Magisk-Modules-Repo/submission/raw/modules/modules.json"


async def check_modules(c: Client):
    date = datetime.datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    sent = await c.send_log_message("<b>Magisk module check started...</b>")
    modules = {}
    updated_modules = []
    excluded_modules = []
    async with httpx.AsyncClient() as client:
        response = await client.get(RAW_URL)
        data = json.loads(response.read())
        last_update = data["last_update"]
        if not config.LAST_UPDATE == last_update:
            config.LAST_UPDATE = last_update
            modules = data["modules"]
            for module in modules:
                module = await parse_module(module)
                _module = await Modules.filter(id=module["id"])
                if len(_module) < 1:
                    await Modules.create(
                        id=module["id"],
                        url=module["url"],
                        name=module["name"],
                        version=module["version"],
                        last_update=module["last_update"],
                    )
                    continue
                else:
                    _module = _module[0]
                    if not _module.version == module["version"]:
                        updated_modules.append(module)
                        await update_module(c, module)
        else:
            return await sent.edit_text(
                f"<b>No updates were detected.</b>\n<b>Date</b>: {date}\n#Sync"
            )
    return await sent.edit_text(
        f"""
<b>Magisk module check finished</b>
    <b>Found</b>: <code>{len(modules)}</code>
    <b>Updated</b>: <code>{len(updated_modules)}</code>
    <b>Excluded</b>: <code>{len(excluded_modules)}</code>
    
<b>Date</b>: {date}
    
Use <code>/modules</code> to check the list of modules.
#Sync #Modules #Magisk
    """
    )


async def get_modules(m: Message):
    date = datetime.datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    text = ""
    modules = await Modules.all()
    modules_list = []
    if len(modules) > 0:
        for module in modules:
            modules_list.append(
                dict(
                    id=module.id,
                    url=module.id,
                    name=module.name,
                    version=module.version,
                    last_update=module.last_update,
                )
            )
        document = io.BytesIO(str(json.dumps(modules_list, indent=4)).encode())
        document.name = "modules.txt"
        return await m.reply_document(
            caption=f"<b>Modules count</b>: <code>{len(modules)}</code>\n<b>Date</b>: {date}\n#Dump #Modules #Magisk",
            document=document,
        )
    else:
        return await m.reply_text("No modules were found.")


async def parse_module(to_parse: Dict) -> Dict:
    module = {
        "id": to_parse["id"],
        "url": to_parse["zip_url"],
        "last_update": to_parse["last_update"],
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(to_parse["prop_url"])
        data = response.read().decode()
        lines = data.split("\n")
        for line in lines:
            try:
                key, value = line.split("=")
                if key in [
                    "api",
                    "author",
                    "description",
                    "name",
                    "version",
                    "versionCode",
                ]:
                    module[key] = value
            except:
                continue
    return module


async def update_module(c: Client, module: Dict):
    document = None
    async with httpx.AsyncClient() as client:
        response = await client.get(module["url"])
        data = response.read()
        document = io.BytesIO(data)
    document.name = (module["name"].replace(" ", "_").replace("-", "")) + ".zip"
    caption = f"""
<b>{module["name"]} {"v" if module["version"][0].isdecimal() else ""}{module["version"]} ({module["versionCode"]})</b>

⚡<i>Magisk Module</i>
⚡<i>{module["description"]}</i>
⚡️<a href="https://github.com/Magisk-Modules-Repo/{module["id"]}">GitHub Repository</a>
    
<b>By</b>: {module["author"]}
<b>Follow</b>: @AndroidRepo
    """
    await c.send_channel_document(
        caption=caption, document=document, force_document=True
    )
    mod = (await Modules.filter(id=module["id"]))[0]
    mod.update_from_dict(
        {
            "description": module["description"],
            "name": module["name"],
            "versionCode": module["versionCode"],
            "version": module["version"],
        }
    )
    await mod.save()
