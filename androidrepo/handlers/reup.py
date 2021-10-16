import asyncio
import html
import os
import re
import time
from datetime import datetime

import aiodown
import humanize
from pyrogram import filters
from pyrogram.errors import FloodWait, MessageIdInvalid, MessageNotModified
from pyrogram.types import Message

from androidrepo.androidrepo import AndroidRepo
from androidrepo.config import LOGS_ID

DOWNLOAD_DIR = "./downloads/"


@AndroidRepo.on_message(filters.sudo & filters.cmd(r"reup (?P<query>.+)"))
async def reupload(c: AndroidRepo, m: Message):
    file_url = m.matches[0]["query"]

    is_url = re.match(r"(http(s)?)?(://)?(www)?(\.)?(.*)\.(.*)", file_url)
    if not is_url:
        await m.reply_text("<b>Error:</b> Enter a valid URL.")
        return

    try:
        file_desc = await c.ask(
            m.chat.id,
            "Send me the file description as markdown...",
            reply_to_message_id=m.message_id,
            filters=filters.sudo,
            timeout=120,
        )
    except asyncio.exceptions.TimeoutError:
        await m.reply_text("Operation cancelled! The description was not provided.")
        return

    if not file_url.startswith(("http://", "https://")):
        file_url = f"https://{file_url}"

    sent = await m.reply_text("<code>Processing...</code>")

    start = datetime.now()

    file_name = os.path.basename(file_url)
    file_path = DOWNLOAD_DIR + file_name

    async with aiodown.Client() as client:
        download = client.add(file_url, file_path)
        await client.start()

        last_update = datetime.now()
        while not download.get_status() == "finished":
            if download.get_status() == "failed":
                await m.reply_text("Download failed!")
                return
            if (datetime.now() - last_update).seconds >= 3:
                text = "<b>Downloading...</b>\n"
                text += f"\n<b>File name</b>: <code>{file_name}</code>"
                text += f"\n<b>Size</b>: {download.get_size_downloaded(human=True, binary=True)}/{download.get_size_total(human=True, binary=True)}"
                text += f"\n<b>Speed</b>: {download.get_speed(human=True, binary=True)}"
                text += (
                    f"\n<b>Elapsed</b>: {humanize.precisedelta(datetime.now() - start)}"
                )
                text += f"\n<b>ETA</b>: {download.get_eta(human=True, precise=True)}"
                text += f"\n<b>Progress</b>: {download.get_progress()}%"
                try:
                    await sent.edit(text)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                except MessageIdInvalid:
                    sent = await m.reply_text(text)
                except MessageNotModified:
                    pass
                last_update = datetime.now()

    last_edit = 0

    async def progress(current: float, total: float):
        nonlocal last_edit
        nonlocal sent
        percent = int(f"{current / total * 100:.0f}")

        text = "<b>Uploading...</b>\n"
        text += f"\n<b>File name</b>: <code>{file_name}</code>"
        text += f"\n<b>Size</b>: {humanize.naturalsize(current)}/{humanize.naturalsize(total)}"
        text += f"\n<b>Elapsed</b>: {humanize.precisedelta(datetime.now() - start)}"
        text += f"\n<b>Progress</b>: {percent}%"
        if last_edit + 1 < int(time.time()) or current == total:
            try:
                await sent.edit(text)
            except FloodWait as e:
                await asyncio.sleep(e.x)
            except MessageIdInvalid:
                sent = await m.reply_text(text)
            except MessageNotModified:
                pass
            last_edit = int(time.time())

    await c.send_channel_document(
        caption=file_desc.text.markdown,
        document=file_path,
        file_name=file_name,
        force_document=True,
        progress=progress,
        parse_mode="MD",
    )

    end = datetime.now()

    await sent.edit(
        f"The file was re-uploaded in <code>{(end - start).microseconds / 1000.0:.2f}</code>ms."
    )
    os.remove(file_path)

    await c.send_log_message(
        LOGS_ID,
        (
            "<b>New re-upload</b>\n"
            f"    <b>Sudo:</b> {m.from_user.mention(html.escape(m.from_user.first_name), style='html')}\n"
            f"    <b>File Name:</b> <code>{file_name}</code>\n\n"
            f"<b>Date:</b> <code>{start.strftime('%H:%M:%S - %d/%m/%Y')}</code>\n#Reupload"
        ),
    )
