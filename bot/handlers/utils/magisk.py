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

import aiodown
import async_files
import asyncio
import datetime
import io
import httpx
import os
import rapidjson as json
import shutil

from pyrogram import Client
from pyrogram.types import Message
from zipfile import ZipFile
from bot.database import Modules
from bot import config
from typing import Dict

RAW_URL = "https://github.com/Magisk-Modules-Repo/submission/raw/modules/modules.json"


async def check_modules(c: Client):
    date = datetime.datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    sent = await c.send_log_message("<b>Magisk module check started...</b>")
    modules = []
    updated_modules = []
    excluded_modules = []
    try:
        async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
            response = await client.get(RAW_URL)
            data = response.json()
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
                            await asyncio.sleep(2)
                            await update_module(c, module)
            else:
                return await sent.edit_text(
                    f"<b>No updates were detected.</b>\n\n<b>Date</b>: {date}\n\nUse <code>/modules</code> to check the list of modules.\n#Sync"
                )
    except httpx.ReadTimeout:
        return await sent.edit_text(
            f"<b>Timeout...</b>\n<b>Date</b>: {date}\n#Sync #Timeout"
        )
    module_ids = list(map(lambda module: module["id"], modules))
    for _module in await Modules.all():
        if _module.id not in module_ids:
            excluded_modules.append(_module)
            for index, module in enumerate(modules):
                if _module.id == module["id"]:
                    del modules[index]
            await _module.delete()
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
    modules = await Modules.all()
    modules_list = []
    if len(modules) > 0:
        for module in modules:
            modules_list.append(
                dict(
                    id=module.id,
                    url=module.url,
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
    async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
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
    file_name = (
        module["name"].replace("-", "").replace(" ", "-").replace("--", "")
        + "_"
        + module["version"]
        + "_"
        + "("
        + module["versionCode"]
        + ")"
        + ".zip"
    )
    file_path = "./downloads/" + file_name
    async with aiodown.Client() as client:
        download = client.add(module["url"], file_path)
        await client.start()
        while not download.is_finished():
            await asyncio.sleep(0.5)
        if download.get_status() == "failed":
            return
    files = []
    extraction_path = None
    with ZipFile(file_path, "r") as old_zip:
        for file in old_zip.namelist():
            if extraction_path is None:
                extraction_path = "./downloads/" + "/".join(file.split("/")[:3])
            path = "./downloads/" + file
            files.append(path)
            old_zip.extract(member=file, path="./downloads/")
        old_zip.close()
    os.remove(file_path)
    with ZipFile(file_path, "w") as new_zip:
        for file in files:
            name = "/".join(file.split("/")[3:])
            if name not in [" ", ""] and not name.startswith("."):
                new_zip.write(file, name)
        new_zip.close()
    try:
        shutil.rmtree(extraction_path)
    except BaseException:
        pass
    caption = f"""
<b>{module["name"]} {"v" if module["version"][0].isdecimal() else ""}{module["version"]} ({module["versionCode"]})</b>

⚡<i>Magisk Module</i>
⚡<i>{module["description"]}</i>
⚡️<a href="https://github.com/Magisk-Modules-Repo/{module["id"]}">GitHub Repository</a>

<b>By</b>: {module["author"]}
<b>Follow</b>: @AndroidRepo
    """
    await c.send_channel_document(
        caption=caption, document=file_path, force_document=True
    )
    os.remove(file_path)
    mod = (await Modules.filter(id=module["id"]))[0]
    mod.update_from_dict(
        {
            "description": module["description"],
            "name": module["name"],
            "versionCode": module["versionCode"],
            "version": module["version"],
            "last_update": module["last_update"],
        }
    )
    await mod.save()
