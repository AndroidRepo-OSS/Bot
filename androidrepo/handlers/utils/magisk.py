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

import asyncio
import io
import os
import shutil
from datetime import datetime
from typing import Dict, List
from zipfile import ZipFile

import aiodown
import httpx
import rapidjson as json
from pyrogram import Client
from pyrogram.types import Message

from androidrepo import config
from androidrepo.database import Magisk, Modules

DOWNLOAD_DIR: str = "./downloads/"
MODULES_URL: str = (
    "https://github.com/Magisk-Modules-Repo/submission/raw/modules/modules.json"
)
MAGISK_URL: str = "https://github.com/topjohnwu/magisk-files/raw/master/{}.json"


async def check_modules(c: Client):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    sent = await c.send_log_message(
        config.LOGS_ID, "<b>Magisk Modules check started...</b>"
    )
    modules = []
    updated_modules = []
    excluded_modules = []
    try:
        async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
            response = await client.get(MODULES_URL)
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
                            version_code=module["versionCode"],
                            last_update=module["last_update"],
                        )
                        continue
                    _module = _module[0]
                    if not _module.version == module["version"] or not int(
                        _module.version_code
                    ) == int(module["versionCode"]):
                        updated_modules.append(module)
                        await asyncio.sleep(2)
                        await update_module(c, module)
            else:
                return await sent.edit_text(
                    f"<b>No updates were detected.</b>\n\n"
                    f"<b>Date</b>: <code>{date}</code>\n"
                    "#Sync #Magisk #Modules"
                )
    except httpx.ReadTimeout:
        return await sent.edit_text(
            "<b>Check timeout...</b>\n"
            f"<b>Date</b>: <code>{date}</code>\n"
            "#Sync #Timeout #Magisk #Modules"
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
<b>Magisk Modules check finished</b>
    <b>Found</b>: <code>{len(modules)}</code>
    <b>Updated</b>: <code>{len(updated_modules)}</code>
    <b>Excluded</b>: <code>{len(excluded_modules)}</code>

<b>Date</b>: <code>{date}</code>
#Sync #Magisk #Modules
    """
    )


async def get_modules(m: Message):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
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
                    version_code=module.version_code,
                    last_update=module.last_update,
                )
            )
        document = io.BytesIO(str(json.dumps(modules_list, indent=4)).encode())
        document.name = "modules.json"
        return await m.reply_document(
            caption=(
                "<b>Magisk Modules</b>\n"
                f"<b>Modules count</b>: <code>{len(modules)}</code>\n"
                f"<b>Date</b>: <code>{date}</code>"
            ),
            document=document,
        )
    return await m.reply_text("No modules were found.")


async def get_magisk(m: Message):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    magisks = await Magisk.all()
    magisks_list = []
    if len(magisks) > 0:
        for magisk in magisks:
            magisks_list.append(
                dict(
                    branch=magisk.branch,
                    version=magisk.version,
                    versionCode=magisk.version_code,
                    link=magisk.link,
                    note=magisk.note,
                )
            )
        document = io.BytesIO(str(json.dumps(magisks_list, indent=4)).encode())
        document.name = "magisk.json"
        return await m.reply_document(
            caption=("<b>Magisk Releases</b>\n" f"<b>Date</b>: <code>{date}</code>"),
            document=document,
        )
    return await m.reply_text("No Magisks found.")


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
                key, value = line.split("=", 1)
                if key in [
                    "api",
                    "author",
                    "description",
                    "name",
                    "version",
                    "versionCode",
                ]:
                    module[key] = value
            except BaseException:
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
    file_path = DOWNLOAD_DIR + file_name
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
                extraction_path = DOWNLOAD_DIR + "/".join(file.split("/")[:3])
            path = DOWNLOAD_DIR + file
            files.append(path)
            old_zip.extract(member=file, path=DOWNLOAD_DIR)
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
            "version_code": module["versionCode"],
            "version": module["version"],
            "last_update": module["last_update"],
        }
    )
    await mod.save()


async def get_changelog(url: str) -> str:
    changelog = ""
    async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
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
                changelog += f"\n{line}"
    return changelog


async def check_magisk(c: Client, m_type: str = "stable"):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    sent = await c.send_log_message(
        config.LOGS_ID, "<b>Magisk Releases check started...</b>"
    )

    TYPES: List[str] = ["beta", "stable", "canary"]
    if m_type not in TYPES:
        return

    URL = MAGISK_URL.format(m_type)
    async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
        response = await client.get(URL)
        data = response.json()
        magisk = data["magisk"]
        _magisk = await Magisk.get_or_none(branch=m_type)
        if _magisk is None:
            await Magisk.create(
                branch=m_type,
                version=magisk["version"],
                version_code=magisk["versionCode"],
                link=magisk["link"],
                note=magisk["note"],
            )
            return await sent.edit_text(
                "<b>No data in the database.</b>\n"
                "<b>Saving Magisk data for the next sync...</b>\n"
                f"    <b>Magisk</b>: <code>{m_type}</code>\n\n"
                f"<b>Date</b>: <code>{date}</code>\n"
                "#Sync #Magisk #Releases"
            )
        elif int(_magisk.version_code) == int(magisk["versionCode"]):
            return await sent.edit_text(
                "<b>No updates were detected.</b>\n"
                f"    <b>Magisk</b>: <code>{m_type}</code>\n\n"
                f"<b>Date</b>: <code>{date}</code>\n"
                "#Sync #Magisk #Releases"
            )
        else:
            file_name = f"Magisk-{magisk['version']}_({magisk['versionCode']}).apk"
            file_path = DOWNLOAD_DIR + file_name
            async with aiodown.Client() as client:
                download = client.add(magisk["link"], file_path)
                await client.start()
                while not download.is_finished():
                    await asyncio.sleep(0.5)
                if download.get_status() == "failed":
                    return

            text = f"<b>Magisk {'v' if magisk['version'][0].isdecimal() else ''}{magisk['version']} ({magisk['versionCode']})</b>\n\n"
            text += f"⚡<i>Magisk {m_type.capitalize()}</i>\n"
            text += "⚡<i>Magisk is a suite of open source software for customizing Android, supporting devices higher than Android 5.0.</i>\n"
            text += "⚡️<a href='https://github.com/topjohnwu/Magisk'>GitHub Repository</a>\n"
            if m_type == "canary":
                changelog = await get_changelog(magisk["note"])
                text += "\n⚙️<b>Changelog</b>"
                text += f"{changelog}\n\n"
            else:
                changelog = magisk["note"]
                text += f"⚡<a href='{changelog}'>Changelog</a>\n\n"
            text += "<b>By:</b> <a href='https://github.com/topjohnwu'>John Wu</a>\n"
            text += "<b>Follow:</b> @AndroidRepo"

            await c.send_channel_document(
                caption=text,
                document=file_path,
                parse_mode="combined",
                force_document=True,
            )
            os.remove(file_path)
            _magisk.update_from_dict(
                {
                    "version": magisk["version"],
                    "versionCode": magisk["versionCode"],
                    "link": magisk["link"],
                    "note": magisk["note"],
                }
            )
            await _magisk.save()
            return await sent.edit_text(
                f"""
<b>Magisk Releases check finished</b>
    <b>Updated</b>: <code>{m_type}</code>
    <b>Version</b>: <code>{magisk['version']} ({magisk['versionCode']})</code>

<b>Date</b>: <code>{date}</code>
#Sync #Magisk #Releases
    """
            )
