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

from bs4 import BeautifulSoup
from requests import get

from pyrogram import Client, filters
from pyrogram.types import Message
from pyromod.helpers import ikb


@Client.on_message(filters.cmd("twrp"))
async def on_twrp_m(c: Client, m: Message):
    command = m.text.split()[0]
    device = m.text[len(command) + 1 :]

    if len(device) < 1:
        return await m.reply_text("No codename provided!")

    url = get(f"https://eu.dl.twrp.me/{device}/")
    if url.status_code == 404:
        return await m.reply_text(f"Couldn't find official TWRP for <b>{device}</b>!\n")
    else:
        reply = f"<b>Latest Official TWRP for {device}:</b>\n"
        page = BeautifulSoup(url.content, "lxml")
        date = page.find("em").text.strip()
        reply += f"<b>Updated:</b> {date}\n"
        trs = page.find("table").find_all("tr")
        row = 2 if trs[0].find("a").text.endswith("tar") else 1
        for i in range(row):
            download = trs[i].find("a")
            dl_link = f"https://eu.dl.twrp.me{download['href']}"
            size = trs[i].find("span", {"class": "filesize"}).text
            keyboard = [[(f"🖇️  Download - {size}", dl_link, "url")]]

        return await m.reply_text(
            f"{reply}", reply_markup=ikb(keyboard), disable_web_page_preview=True
        )
