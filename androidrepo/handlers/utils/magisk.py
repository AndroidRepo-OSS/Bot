# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import asyncio
import io
import os
import shutil
from datetime import datetime
from typing import Dict, List, Union
from zipfile import ZipFile

import aiodown
import httpx
import rapidjson as json
from pyrogram import Client
from pyrogram.types import Message

from androidrepo import config
from androidrepo.database import Magisk, Modules
from androidrepo.handlers.utils import get_changelog
from androidrepo.utils import httpx_timeout

DOWNLOAD_DIR: str = "./downloads/"
MAGISK_URL: str = "https://github.com/topjohnwu/magisk-files/raw/master/{}.json"


async def check_modules(c: Client):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    modules = []
    updated_modules = []
    excluded_modules = []
    try:
        async with httpx.AsyncClient(
            http2=True, timeout=httpx_timeout, follow_redirects=True
        ) as client:
            response = await client.get(config.MODULES_URL)
            if response.status_code in [500, 503, 504, 505]:
                return await c.send_log_message(
                    config.LOGS_ID,
                    f"<b>GitHub is in serious trouble, I couldn't complete the verification..</b>\n\n"
                    f"<b>Date</b>: <code>{date}</code>\n"
                    "#Sync #Magisk #Modules",
                )
            data = response.json()
            last_update = data["last_update"]
            if config.LAST_UPDATE == last_update:
                return
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
                if _module.version != module["version"] or int(
                    _module.version_code
                ) != int(module["versionCode"]):
                    updated_modules.append(module)
                    await asyncio.sleep(2)
                    await update_module(c, module)
    except httpx.ReadTimeout:
        return await c.send_log_message(
            config.LOGS_ID,
            "<b>Check timeout...</b>\n"
            f"<b>Date</b>: <code>{date}</code>\n"
            "#Sync #Timeout #Magisk #Modules",
        )
    module_ids = list(map(lambda module: module["id"], modules))
    for _module in await Modules.all():
        if _module.id not in module_ids:
            excluded_modules.append(_module)
            for index, module in enumerate(modules):
                if _module.id == module["id"]:
                    del modules[index]
            await _module.delete()
    return await c.send_log_message(
        config.LOGS_ID,
        f"""
<b>Magisk Modules check finished</b>
    <b>Found</b>: <code>{len(modules)}</code>
    <b>Updated</b>: <code>{len(updated_modules)}</code>
    <b>Excluded</b>: <code>{len(excluded_modules)}</code>

<b>Date</b>: <code>{date}</code>
#Sync #Magisk #Modules
    """,
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
                    changelog=magisk.changelog,
                )
            )
        document = io.BytesIO(str(json.dumps(magisks_list, indent=4)).encode())
        document.name = "magisk.json"
        return await m.reply_document(
            caption=("<b>Magisk Releases</b>\n" f"<b>Date</b>: <code>{date}</code>"),
            document=document,
        )
    return await m.reply_text("No Magisks found.")


async def parse_module(to_parse: Union[Dict, str]) -> Dict:
    if isinstance(to_parse, Dict):
        module = {
            "id": to_parse["id"],
            "url": to_parse["zip_url"],
            "last_update": to_parse["last_update"],
        }
        prop_url = to_parse["prop_url"]

    if isinstance(to_parse, str):
        prop_url = to_parse

    async with httpx.AsyncClient(
        http2=True, timeout=httpx_timeout, follow_redirects=True
    ) as client:
        response = await client.get(prop_url)
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

<b>By:</b> {module["author"]}
<b>Follow:</b> @AndroidRepo
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


async def check_magisk(c: Client):
    TYPES: List[str] = ["stable", "beta", "canary"]
    for magisk in TYPES:
        await update_magisk(c, magisk)


async def update_magisk(c: Client, m_type: str):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    URL = MAGISK_URL.format(m_type)
    async with httpx.AsyncClient(
        http2=True, timeout=httpx_timeout, follow_redirects=True
    ) as client:
        response = await client.get(URL)
        data = response.json()
        magisk = data["magisk"]
        _magisk = await Magisk.get_or_none(branch=m_type)
        if _magisk is None:
            chg = await get_changelog(magisk["note"])
            await Magisk.create(
                branch=m_type,
                version=magisk["version"],
                version_code=magisk["versionCode"],
                link=magisk["link"],
                note=magisk["note"],
                changelog=chg,
            )
            return await c.send_log_message(
                config.LOGS_ID,
                "<b>No data in the database.</b>\n"
                "<b>Saving Magisk data for the next sync...</b>\n"
                f"    <b>Magisk</b>: <code>{m_type}</code>\n\n"
                f"<b>Date</b>: <code>{date}</code>\n"
                "#Sync #Magisk #Releases",
            )
        if _magisk.version == magisk["version"] or int(_magisk.version_code) == int(
            magisk["versionCode"]
        ):
            return

        # do not send the Magisk Beta if it is the same version of Magisk Stable
        r = await client.get(MAGISK_URL.format("beta"))
        magiskb = r.json()
        _magisks = await Magisk.get_or_none(branch="stable")
        if not m_type == "beta" or not magiskb["magisk"]["version"] == _magisks.version:
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
            text += f"⚡<a href='{magisk['note']}'>Changelog</a>\n\n"
            text += "<b>By:</b> <a href='https://github.com/topjohnwu'>John Wu</a>\n"
            text += "<b>Follow:</b> @AndroidRepo"

            await c.send_channel_document(
                caption=text,
                document=file_path,
                parse_mode="combined",
                force_document=True,
            )
            os.remove(file_path)

        chg = await get_changelog(magisk["note"])
        _magisk.update_from_dict(
            {
                "version": magisk["version"],
                "version_code": int(magisk["versionCode"]),
                "link": magisk["link"],
                "note": magisk["note"],
                "changelog": chg,
            }
        )
        await _magisk.save()
        return await c.send_log_message(
            config.LOGS_ID,
            "<b>Magisk Releases check finished</b>\n"
            f"    <b>Updated</b>: <code>{m_type}</code>\n"
            f"    <b>Version</b>: <code>{magisk['version']} ({magisk['versionCode']})</code>\n\n"
            f"<b>Date</b>: <code>{date}</code>\n"
            "#Sync #Magisk #Releases",
        )
