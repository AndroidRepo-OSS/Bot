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

import html
from typing import Union

from pyrogram import filters
from pyrogram.types import CallbackQuery, Message

from ..androidrepo import AndroidRepo


@AndroidRepo.on_message(filters.cmd("start"))
@AndroidRepo.on_callback_query(filters.regex("^start_back$"))
async def start(c: AndroidRepo, m: Union[Message, CallbackQuery]):
    keyboard = []
    text = f"Hi <b>{html.escape(m.from_user.first_name)}</b>, I am the <b>official bot of the Android Repository channel</b>."
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
                        f"http://t.me/{c.me.username}?start",
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


@AndroidRepo.on_message(filters.cmd("help"))
@AndroidRepo.on_callback_query(filters.regex("^help$"))
async def on_help(c: AndroidRepo, m: Union[Message, CallbackQuery]):
    chat_type = m.chat.type if isinstance(m, Message) else m.message.chat.type
    if chat_type == "private":
        keyboard = [
            [
                ("🔧 Utilities", "help_commands"),
                ("💭 Contact", "help_contact"),
                ("📝 Requests", "help_requests"),
            ],
            [("🔙 Back", "start_back")],
        ]
        text = "Choose a category to get help!"
    else:
        keyboard = [
            [
                (
                    "Click here for help!",
                    f"http://t.me/{c.me.username}?start",
                    "url",
                )
            ]
        ]
        text = "I am the <b>official bot of the Android Repository channel</b>, click the button below to find out what I can do for you."
    if isinstance(m, Message):
        await m.reply_text(
            text,
            reply_markup=c.ikb(keyboard),
            disable_web_page_preview=True,
        )
    if isinstance(m, CallbackQuery):
        await m.message.edit_text(
            text,
            reply_markup=c.ikb(keyboard),
            disable_web_page_preview=True,
        )


@AndroidRepo.on_callback_query(filters.regex("^help_requests$"))
async def help_requests(c: AndroidRepo, m: CallbackQuery):
    keyboard = [[("🔙 Back", "help")]]
    text = (
        "<b>Here is what I can do for you:</b>\n"
        " - <code>/request (link)</code>: Make requests for files that could be sent on the channel.\n"
        " - <code>/myrequests</code>: See all the requests you have already made.\n"
        " - <code>/cancelrequest (ID)</code>: Cancel the request for the specified ID.\n\n"
        "<b>NOTE:</b>\nYou can request apps, Magisk modules, recovery files and other Android related files (don't ask for piracy)."
    )
    await m.message.edit_text(
        text,
        reply_markup=c.ikb(keyboard),
        disable_web_page_preview=True,
    )


@AndroidRepo.on_callback_query(filters.regex("^help_contact$"))
async def help_contact(c: AndroidRepo, m: CallbackQuery):
    keyboard = [[("🔙 Back", "help")]]
    text = (
        "<b>Here is what I can do for you:</b>\n"
        " - <code>/contact</code>: Enters contact mode.\n"
        " - <code>/quit</code>: Get out of contact mode.\n\n"
        "<b>NOTE:</b>\nWhen entering contact mode all your messages (except commands) will be sent to @AndroidRepo staff, with this mode you will be able to chat with staff easily."
    )
    await m.message.edit_text(
        text,
        reply_markup=c.ikb(keyboard),
        disable_web_page_preview=True,
    )


@AndroidRepo.on_callback_query(filters.regex("^help_commands$"))
async def help_commands(c: AndroidRepo, m: CallbackQuery):
    keyboard = [[("🔙 Back", "help")]]
    text = (
        "<b>Here is what I can do for you:</b>\n"
        " - <code>/magisk (branch)</code>: Returns the latest version of Magsik in the specified branch.\n"
        "<b>Available Magisk branches:</b> <code>stable</code>, <code>beta</code>, <code>canary</code>."
    )
    await m.message.edit_text(
        text,
        reply_markup=c.ikb(keyboard),
        disable_web_page_preview=True,
    )
