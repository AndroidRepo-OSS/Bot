# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import httpx
from bs4 import BeautifulSoup
from pyrogram import filters
from pyrogram.types import Message

from androidrepo.utils import httpx_timeout

from ..androidrepo import AndroidRepo


@AndroidRepo.on_message(filters.cmd("twrp"))
async def twrp(c: AndroidRepo, m: Message):
    command = m.text.split()[0]
    device = m.text[len(command) :]

    if len(device) < 1:
        await m.reply_text("Use <code>/twrp (device)</code>.")
        return

    if len(device) > 1:
        device = device[1:]

    async with httpx.AsyncClient(
        http2=True, timeout=httpx_timeout, follow_redirects=True
    ) as client:
        r = await client.get(f"https://eu.dl.twrp.me/{device}/")
        if r.status_code == 404:
            text = f"Couldn't find twrp downloads for <code>{device}</code>!"
            await m.reply_text(text)
            return

    page = BeautifulSoup(r.content, "lxml")
    date = page.find("em").text.strip()
    trs = page.find("table").find_all("tr")
    row = 2 if trs[0].find("a").text.endswith("tar") else 1

    for i in range(row):
        download = trs[i].find("a")
        dl_link = f"https://dl.twrp.me{download['href']}"
        dl_file = download.text
        size = trs[i].find("span", {"class": "filesize"}).text

    text = f"<b>Latest TWRP for:</b> <code>{device}</code>\n"
    text += f"<b>File:</b> <code>{dl_file}</code>\n"
    text += f"<b>Updated:</b> <code>{date}</code>"
    keyboard = [[(f"⬇️ Download - {size}", dl_link, "url")]]

    await m.reply_text(text, reply_markup=c.ikb(keyboard))
