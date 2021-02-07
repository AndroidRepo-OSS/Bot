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

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyromod.helpers import ikb


@Client.on_message(filters.cmd("start"))
async def start(c: Client, m: Message):
    keyboard = []
    text = "Hi, I'm the <b>official Android Repository Bot</b>."
    if m.chat.type == "private":
        keyboard.append(
            [
                ("💬 Group", "https://t.me/AndroidRepo_chat", "url"),
                ("📢 Channel", "https://t.me/AndroidRepo", "url"),
            ]
        )
        keyboard.append([("❔ Help", "help")])
    else:
        keyboard.append(
            [
                (
                    "Click here for help!",
                    f"http://t.me/{(await c.get_me()).username}?start",
                    "url",
                )
            ]
        )
    await m.reply_text(
        text,
        reply_markup=ikb(keyboard),
    )


@Client.on_callback_query(filters.regex("^start_back$"))
async def start_back(c: Client, m: CallbackQuery):
    text = "Hi, I'm the <b>official Android Repository Bot</b>."
    keyboard = ikb(
        [
            [
                ("💬 Group", "https://t.me/AndroidRepo_chat", "url"),
                ("📢 Channel", "https://t.me/AndroidRepo", "url"),
            ],
            [("❔ Help", "help")],
        ]
    )
    await m.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^help$"))
async def help(c: Client, m: CallbackQuery):
    keyboard = ikb(
        [
            [("🔧 Utilities", "help_commands"), ("💭 Requests", "help_requests")],
            [("<-", "start_back")],
        ]
    )
    text = "Choose a category for help!"
    await m.message.edit_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


@Client.on_callback_query(filters.regex("^help_requests$"))
async def help_requests(c: Client, m: CallbackQuery):
    keyboard = ikb([[("<-", "help")]])
    text = (
        "<b>Here is what I can do for you:</b>\n\n"
        "You can also place requests for the @AndroidRepo staff using the #request in the bot's PM or in the @AndroidRepo_chat.\n\n"
        "<b>i.e:</b> <code>#request Update the EdXposed module</code>\n\n"
        "You can request modules, apps, and other files, if you are a developer also feel free to send us your projects."
    )
    await m.message.edit_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


@Client.on_callback_query(filters.regex("^help_commands$"))
async def help_commands(c: Client, m: CallbackQuery):
    keyboard = ikb([[("<-", "help")]])
    text = (
        "<b>Here is what I can do for you:</b>\n\n"
        " - <code>/magisk (type)</code>: Returns the latest version of Magisk.\n"
        " - <code>/twrp (codename)</code>: Return the latest official version of TWRP to the specified device.\n\n"
        "<b>Available Magisk types:</b> <code>stable</code>, <code>beta</code>, <code>canary</code>."
    )
    await m.message.edit_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
