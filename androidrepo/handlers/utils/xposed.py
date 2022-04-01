# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import asyncio
import io
import os
from datetime import datetime

import aiodown
import httpx
import rapidjson as json
from pyrogram import Client
from pyrogram.types import Message

from androidrepo import config
from androidrepo.database import LSPosed
from androidrepo.utils import httpx_timeout

DOWNLOAD_DIR: str = "./downloads/LSPosed/"
LSPOSED_URL: str = "https://lsposed.github.io/LSPosed/release/{}.json"


async def get_lsposed(m: Message):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    lsposeds = await LSPosed.all()
    lsposed_list = []
    if len(lsposeds) > 0:
        for lsposed in lsposeds:
            lsposed_list.append(
                dict(
                    branch=lsposed.branch,
                    version=lsposed.version,
                    versionCode=lsposed.version_code,
                    link=lsposed.link,
                    changelog=lsposed.changelog,
                )
            )
        document = io.BytesIO(str(json.dumps(lsposed_list, indent=4)).encode())
        document.name = "lsposed.json"
        return await m.reply_document(
            caption=("<b>LSPosed Releases</b>\n" f"<b>Date</b>: <code>{date}</code>"),
            document=document,
        )
    return await m.reply_text("No LSPosed found.")


async def check_lsposed(c: Client):
    TYPES: List[str] = ["riru", "zygisk"]
    for lsposed in TYPES:
        await update_lsposed(c, lsposed)
        await asyncio.sleep(5)


async def update_lsposed(c: Client, branch: str):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    async with httpx.AsyncClient(
        http2=True, timeout=httpx_timeout, follow_redirects=True
    ) as client:
        response = await client.get(LSPOSED_URL.format(branch))
        if response.status_code in [500, 503, 504, 505]:
            return await c.send_log_message(
                config.LOGS_ID,
                f"<b>GitHub is in serious trouble, I couldn't complete the verification..</b>\n\n"
                f"<b>Date</b>: <code>{date}</code>\n"
                "#Sync #LSPosed #Releases",
            )
        data = response.json()
        _lsposed = await LSPosed.get_or_none(branch=branch)
        if _lsposed is None:
            await LSPosed.create(
                branch=branch,
                version=data["version"],
                version_code=data["versionCode"],
                link=data["zipUrl"],
                changelog=data["changelog"],
            )
            return await c.send_log_message(
                config.LOGS_ID,
                "<b>No data in the database.</b>\n"
                "<b>Saving LSPosed data for the next sync...</b>\n"
                f"    <b>LSPosed</b>: <code>{branch}</code>\n\n"
                f"<b>Date</b>: <code>{date}</code>\n"
                "#Sync #LSPosed #Releases",
            )
        if _lsposed.version == data["version"] or int(_lsposed.version_code) == int(
            data["versionCode"]
        ):
            return

        async with aiodown.Client() as client:
            file_name = os.path.basename(data["zipUrl"])
            file_path = DOWNLOAD_DIR + file_name
            download = client.add(data["zipUrl"], file_path)
            await client.start()
            while not download.is_finished():
                await asyncio.sleep(0.5)
            if download.get_status() == "failed":
                return

        caption = f"<b>{branch.capitalize()} - LSPosed {data['version']} ({data['versionCode']})</b>\n\n"
        caption += "⚡<i>Magisk Module</i>\n"
        if branch == "zygisk":
            caption += "⚡<i>Another enhanced implementation of Xposed Framework. Requires Magisk 24.0+ and Zygisk enabled.</i>\n"
        if branch == "riru":
            caption += "⚡<i>Another enhanced implementation of Xposed Framework. Requires Riru 25.0.1 or above installed.</i>\n"
        caption += (
            "⚡️<a href='https://github.com/LSPosed/LSPosed'>GitHub Repository</a>\n"
        )
        caption += f"⚡️<a href='{data['changelog']}'>Changelog</a>\n"
        caption += "\n<b>By:</b> LSPosed Developers\n"
        caption += "<b>Follow:</b> @AndroidRepo"

        await c.send_channel_document(
            caption=caption,
            document=file_path,
            parse_mode="combined",
            force_document=True,
        )
        os.remove(file_path)

        _lsposed.update_from_dict(
            {
                "version": data["version"],
                "version_code": int(data["versionCode"]),
                "link": data["zipUrl"],
                "changelog": data["changelog"],
            }
        )
        await _lsposed.save()
        return await c.send_log_message(
            config.LOGS_ID,
            "<b>LSPosed Releases check finished</b>\n"
            f"    <b>Updated</b>: <code>{branch}</code>\n"
            f"    <b>Version</b>: <code>{data['version']} ({data['versionCode']})</code>\n\n"
            f"<b>Date</b>: <code>{date}</code>\n"
            "#Sync #LSPosed #Releases",
        )
