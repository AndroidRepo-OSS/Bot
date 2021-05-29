import asyncio
import html
import os
import random
import re
import time
from datetime import datetime, timedelta

import async_files
import httpx
import humanize
from pyrogram import filters
from pyrogram.errors import FloodWait, MessageIdInvalid, MessageNotModified
from pyrogram.types import Message

from androidrepo.androidrepo import AndroidRepo
from androidrepo.config import LOGS_ID

DOWNLOAD_DIR = "./downloads/"


@AndroidRepo.on_message(filters.sudo & filters.cmd(r"reup (?P<query>.+)"))
async def reupload(c: AndroidRepo, m: Message):
    query = m.matches[0]["query"]

    if "|" in query:
        file_url, file_name = query.split("|")
        file_name = file_name.strip()
    else:
        file_url = query
        file_name = None

    file_url = file_url.strip()

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

    async with httpx.AsyncClient(http2=True) as client:
        try:
            async with client.stream("GET", file_url) as response:
                num_bytes_total = int(response.headers["Content-Length"])
                num_bytes_downloaded = response.num_bytes_downloaded

                if response.status_code == 200:
                    if not file_name:
                        file_name = os.path.basename(file_url)

                    await c.send_log_message(
                        LOGS_ID,
                        (
                            "<b>New re-upload</b>\n"
                            f"    <b>Sudo:</b> {m.from_user.mention(html.escape(m.from_user.first_name), style='html')}\n"
                            f"    <b>File Name:</b> <code>{file_name}</code>\n\n"
                            f"<b>Date:</b> <code>{start.strftime('%H:%M:%S - %d/%m/%Y')}</code>\n#Reupload"
                        ),
                    )

                    file_path = DOWNLOAD_DIR + file_name

                    if not os.path.exists(DOWNLOAD_DIR):
                        os.mkdir(DOWNLOAD_DIR)

                    while os.path.exists(file_path):
                        file_path += f" ({random.randint(1, 9999)})"

                    async with async_files.FileIO(file_path, "wb") as file:
                        last_update = datetime.now()

                        async for chunk in response.aiter_bytes():
                            await file.write(chunk)

                            percent = int(
                                f"{num_bytes_downloaded / num_bytes_total * 100:.0f}"
                            )

                            if (datetime.now() - last_update).seconds >= 3:
                                text = "<b>Downloading...</b>\n"
                                text += f"\n<b>File name</b>: <code>{file_name}</code>"
                                text += f"\n<b>Size</b>: {humanize.naturalsize(num_bytes_downloaded, binary=True)}/{humanize.naturalsize(num_bytes_total, binary=True)}"
                                try:
                                    speed = num_bytes_downloaded / (
                                        (datetime.now() - start).seconds + 1
                                    )
                                except ZeroDivisionError:
                                    speed = 0
                                text += f"\n<b>Speed</b>: {humanize.naturalsize(speed, binary=True)}"
                                text += f"\n<b>Elapsed</b>: {humanize.precisedelta(datetime.now() - start)}"
                                try:
                                    eta = timedelta(
                                        seconds=(num_bytes_total - num_bytes_downloaded)
                                        / speed
                                    )
                                except ZeroDivisionError:
                                    eta = timedelta(seconds=0)
                                text += f"\n<b>ETA</b>: {humanize.precisedelta(eta)}"
                                text += f"\n<b>Progress</b>: {percent}%"
                                try:
                                    await sent.edit(text)
                                except FloodWait as e:
                                    await asyncio.sleep(e.x)
                                except MessageIdInvalid:
                                    sent = await m.reply_text(text)
                                except MessageNotModified:
                                    pass
                                last_update = datetime.now()

                            num_bytes_downloaded = response.num_bytes_downloaded

                        await file.close()

                elif response.status_code == 403:
                    await sent.edit("The file has been blocked by the server.")
                elif response.status_code == 404:
                    await sent.edit("The specified url was not found.")
                else:
                    await sent.edit(f"<b>Error {response.status_code}</b>")
        except BaseException as e:
            await sent.edit(f"<b>Error:</b> <code>{e.__class__.__name__}</code> - {e}")
            return
        finally:
            await client.aclose()

    try:
        if os.path.isfile(file_path):
            last_edit = 0

            async def progress(current: float, total: float):
                nonlocal last_edit
                nonlocal sent
                percent = int(f"{current / total * 100:.0f}")

                text = "<b>Uploading...</b>\n"
                text += f"\n<b>File name</b>: <code>{file_name}</code>"
                text += f"\n<b>Size</b>: {humanize.naturalsize(current)}/{humanize.naturalsize(total)}"
                text += (
                    f"\n<b>Elapsed</b>: {humanize.precisedelta(datetime.now() - start)}"
                )
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
        else:
            await sent.edit("The file to upload was not found.")
    except BaseException as e:
        await sent.edit(f"<b>Error:</b> <code>{e.__class__.__name__}</code> - {e}")
        return
