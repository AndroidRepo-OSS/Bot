# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import asyncio
import os
from datetime import datetime

import aiodown
import httpx
from pyrogram import Client
from pyrogram.enums import ParseMode

from androidrepo import config
from androidrepo.database.quickpic import (
    create_quickpic,
    get_quickpic_by_branch,
    update_quickpic_from_dict,
)

DOWNLOAD_DIR: str = "./downloads/QuickPic/"
QUICKPIC_URL: str = "https://github.com/WSTxda/QP-Gallery-Releases/raw/master/OTA%20updater/updater.json"


async def check_quickpic(c: Client, branch: str = "stable"):
    date = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
        response = await client.get(QUICKPIC_URL)
        if response.status_code in [500, 503, 504, 505]:
            return await c.send_log_message(
                config.LOGS_ID,
                f"<b>GitHub is in serious trouble, I couldn't complete the verification..</b>\n\n"
                f"<b>Date</b>: <code>{date}</code>\n"
                "#Sync #QuickPic #Releases",
            )
        data = response.json()["stable"]
        _quickpic = await get_quickpic_by_branch(branch=branch)
        if _quickpic is None:
            await create_quickpic(
                branch=branch,
                version=data["current_version"],
                link=data["download_url"],
                changelog=data["changelog"],
            )
            return await c.send_log_message(
                config.LOGS_ID,
                "<b>No data in the database.</b>\n"
                "<b>Saving QuickPic data for the next sync...</b>\n"
                f"    <b>QuickPic</b>: <code>{branch}</code>\n\n"
                f"<b>Date</b>: <code>{date}</code>\n"
                "#Sync #QuickPic #Releases",
            )
        if _quickpic["version"] == data["current_version"]:
            return

        response = await client.get(
            "https://api.github.com/repos/WSTxda/QP-Gallery-Releases/releases/latest"
        )
        qp = response.json()
        version = qp["tag_name"]

        async with aiodown.Client() as client:
            file_name = os.path.basename(data["download_url"])
            file_path = DOWNLOAD_DIR + file_name
            download = client.add(data["download_url"], file_path)
            await client.start()
            while not download.is_finished():
                await asyncio.sleep(0.5)
            if download.get_status() == "failed":
                return

        caption = f"<b>QuickPic Mode {version}</b>\n\n"
        caption += (
            "⚡<i>A simple, lightweight and materialized gallery for Android.</i>\n"
        )
        caption += f"\n⚙<b>Changelog:</b>\n{data['changelog']}\n"
        caption += "\n<b>By:</b> @WSTprojects\n"
        caption += "<b>Follow:</b> @AndroidRepo"

        await c.send_channel_document(
            caption=caption,
            document=file_path,
            parse_mode=ParseMode.DEFAULT,
            force_document=True,
        )
        os.remove(file_path)

        await update_quickpic_from_dict(
            branch=branch,
            data={
                "version": data["current_version"],
                "link": data["download_url"],
                "changelog": data["changelog"],
            },
        )
        return await c.send_log_message(
            config.LOGS_ID,
            "<b>QuickPic Releases check finished</b>\n"
            f"    <b>Updated</b>: <code>{branch}</code>\n"
            f"    <b>Version</b>: <code>{version} ({data['current_version']})</code>\n\n"
            f"<b>Date</b>: <code>{date}</code>\n"
            "#Sync #LSPosed #Releases",
        )
