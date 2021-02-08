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

import shutil

from pyrogram import Client, filters
from pyrogram.types import Message
from ..config import CHANNEL_ID


@Client.on_message(filters.sudo & filters.cmd("reup") & filters.reply)
async def on_reup_m(c: Client, m: Message):
    command = m.text.split()[0]
    desc = m.text[len(command) + 1 :]

    await m.reply_text("Starting re-upload...")

    try:
        download_path = await c.download_media(m.reply_to_message)
    except BaseException as e:
        return await m.reply_text(f"<b>Error!</b>\n<code>{e}</code>")

    try:
        await c.send_document(
            chat_id=CHANNEL_ID, document=download_path, caption=f"{desc}"
        )
        shutil.rmtree("bot/downloads/")
    except BaseException as e:
        return await m.reply_text(f"<b>Error!</b>\n<code>{e}</code>")
