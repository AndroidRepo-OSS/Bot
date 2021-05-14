# This file is part of AndroidRepo (Telegram Bot)
# Copyright (C) 2021 AmanoTeam

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

from typing import Union

from pyrogram import filters
from pyrogram.types import CallbackQuery, Message

from ..androidrepo import AndroidRepo


@AndroidRepo.on_message(filters.cmd("start"))
@AndroidRepo.on_callback_query(filters.regex("^start_back$"))
async def start(c: AndroidRepo, m: Union[Message, CallbackQuery]):
    keyboard = []
    text = "Hi, I'm the <b>official Android Repository Bot</b>."
    keyboard.append(
        [
            ("💬 Group", "https://t.me/AndroidRepo_chat", "url"),
            ("📢 Channel", "https://t.me/AndroidRepo", "url"),
        ]
    )
    if isinstance(m, Message):
        if m.chat.type == "private":
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
            reply_markup=c.ikb(keyboard),
            disable_web_page_preview=True,
        )
    if isinstance(m, CallbackQuery):
        keyboard.append([("❔ Help", "help")])
        await m.message.edit_text(
            text,
            reply_markup=c.ikb(keyboard),
            disable_web_page_preview=True,
        )


@AndroidRepo.on_message(filters.cmd("help") & filters.private)
@AndroidRepo.on_callback_query(filters.regex("^help$"))
async def on_help(c: AndroidRepo, m: Union[Message, CallbackQuery]):
    keyboard = c.ikb(
        [
            [("🔧 Utilities", "help_commands"), ("💭 Requests", "help_requests")],
            [("<-", "start_back")],
        ]
    )
    text = "Choose a category for help!"
    if isinstance(m, Message):
        await m.reply_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    if isinstance(m, CallbackQuery):
        await m.message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )


@AndroidRepo.on_callback_query(filters.regex("^help_requests$"))
async def help_requests(c: AndroidRepo, m: CallbackQuery):
    keyboard = c.ikb([[("<-", "help")]])
    text = (
        "<b>Here is what I can do for you:</b>\n\n"
        "You can also place requests for the @AndroidRepo staff using the #request in the bot's PM.\n\n"
        "<b>i.e:</b> <code>#request Update the EdXposed module</code>\n\n"
        "You can request modules, apps, and other files, if you are a developer also feel free to send us your projects."
    )
    await m.message.edit_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


@AndroidRepo.on_callback_query(filters.regex("^help_commands$"))
async def help_commands(c: AndroidRepo, m: CallbackQuery):
    keyboard = c.ikb([[("<-", "help")]])
    text = (
        "<b>Here is what I can do for you:</b>\n\n"
        " - <code>/magisk (type)</code>: Returns the latest version of Magisk.\n"
        "<b>Available Magisk types:</b> <code>stable</code>, <code>beta</code>, <code>canary</code>."
    )
    await m.message.edit_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
