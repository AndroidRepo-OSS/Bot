# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import time
from typing import List

import httpx
import rapidjson as json
from httpx import TimeoutException
from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.types import Message

from androidrepo.bot import AndroidRepo

API_HOST = "https://api.orangefox.download/v3"
TYPES: List[str] = ["stable", "beta"]


@AndroidRepo.on_message(filters.cmd("start ofox_(?P<args>.+)") & filters.private)
async def orangefox_pm(c: AndroidRepo, m: Message):
    args = m.matches[0]["args"]
    await orangefox_list(c, m, args)


@AndroidRepo.on_message(filters.cmd("ofox$"))
@AndroidRepo.on_message(filters.cmd("ofox beta$"))
async def orangefox_list(c: AndroidRepo, m: Message, build_type: str = None):
    if build_type is None:
        args = m.text.split(" ")
        if len(args) == 1:
            build_type = "stable"
        else:
            build_type = args[1]

    if m.chat.type == ChatType.PRIVATE:
        async with httpx.AsyncClient(
            http2=True, timeout=40, follow_redirects=True
        ) as client:
            text = f"<b>OrangeFox Recovery <i>{build_type}</i> is currently avaible for:</b>"
            data = await client.get(
                f"{API_HOST}/devices/?release_type={build_type}&sort=device_name_asc"
            )
            devices = json.loads(data.text)
            for device in devices["data"]:
                text += (
                    f"\n - {device['full_name']} (<code>{device['codename']}</code>)"
                )

            await m.reply_text(text)
    else:
        text = f"Click the button below to receive the list of devices with <code>{build_type}</code> releases of OrangeFox."
        text += "\nUse <code>/ofox (device)</code> or <code>/ofox (device) beta</code> to get the last release for the specified device."

        keyboard = [
            [
                (
                    "Got to PM!",
                    f"https://t.me/{c.me.username}?start=ofox_{build_type}",
                    "url",
                )
            ]
        ]

        await m.reply_text(text, reply_markup=c.ikb(keyboard))


@AndroidRepo.on_message(filters.cmd(r"ofox (?P<args>.+)"))
async def orangefox(c: AndroidRepo, m: Message):
    args = m.matches[0]["args"].split(" ")
    if len(args) in (1, 2):
        codename = args[0]
        build_type = "stable"

    if len(args) == 2:
        build_type = args[1]

    async with httpx.AsyncClient(
        http2=True, timeout=40, follow_redirects=True
    ) as client:
        try:
            data = await client.get(f"{API_HOST}/devices/get?codename={codename}")
        except TimeoutException:
            await m.reply_text("Sorry, I couldn't connect to the OranegFox API!")
            return

        if data.status_code == 404:
            await m.reply_text("Couldn't find any results matching your query.")
            return

        device = json.loads(data.text)

        data = await client.get(
            f"{API_HOST}/releases/?codename={codename}&type={build_type}&sort=date_desc&limit=1"
        )
        if data.status_code == 404 and build_type in TYPES:
            url = f"https://orangefox.download/device/{device['codename']}"
            keyboard = [[("Device's page", url, "url")]]
            await m.reply_text(
                f"⚠️ There is no '<b>{build_type}</b>' releases for <b>{device['full_name']}</b>.",
                reply_markup=c.ikb(keyboard),
            )
            return

        if build_type not in TYPES:
            await m.reply_text(
                f"⚠️ There is no type '<b>{build_type}</b>', there is only beta and stable."
            )
            return

        find_id = json.loads(data.text)
        for build in find_id["data"]:
            file_id = build["_id"]

        data = await client.get(f"{API_HOST}/releases/get?_id={file_id}")
        release = json.loads(data.text)
        if data.status_code == 404:
            await m.reply_text("Couldn't find any results matching your query.")
            return

        text = f"<u><b>OrangeFox Recovery <i>{build_type}</i> release</b></u>\n"
        text += f"  <b>Device:</b> {device['full_name']} (<code>{device['codename']}</code>)\n"
        text += f"  <b>Version:</b> {release['version'] }\n"
        of_release_date = time.strftime("%d/%m/%Y", time.localtime(release["date"]))
        text += f"  <b>Release date:</b> {of_release_date}\n"
        text += f"  <b>Maintainer:</b> {device['maintainer']['name']}\n"
        changelog = release["changelog"]
        text += "  <u><b>Changelog:</b></u>\n"
        for entry_num in range(len(changelog)):
            if entry_num == 10:
                break
            text += f"    - {changelog[entry_num]}\n"

        mirror = release["mirrors"]["US"]
        url = mirror if mirror is not None else release["url"]
        keyboard = [[("⬇️ Download", url, "url")]]
        await m.reply_text(
            text, reply_markup=c.ikb(keyboard), disable_web_page_preview=True
        )
