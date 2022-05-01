# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import html
from typing import Union

from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery, Message

from androidrepo.bot import AndroidRepo


@AndroidRepo.on_message(filters.cmd("start$"))
@AndroidRepo.on_callback_query(filters.regex("^start_back$"))
async def start(c: AndroidRepo, union: Union[Message, CallbackQuery]):
    is_callback = isinstance(union, CallbackQuery)
    m = union.message if is_callback else union
    user = union.from_user

    text = f"Hi <b>{html.escape(user.first_name)}</b>, I am the <b>official bot of the Android Repository channel</b>."
    keyboard = [
        (
            "Click here for help!",
            f"http://t.me/{c.me.username}?start=help",
            "url",
        )
    ]
    if m.chat.type == ChatType.PRIVATE:
        keyboard = [
            (
                ("ℹ️ About", "about"),
                ("❔ Help", "help"),
            )
        ]

    await (m.edit_text if is_callback else m.reply_text)(
        text,
        reply_markup=c.ikb(keyboard),
        disable_web_page_preview=True,
    )


@AndroidRepo.on_message(filters.cmd("start help") & filters.private)
@AndroidRepo.on_message(filters.cmd("help$"))
@AndroidRepo.on_callback_query(filters.regex("^help$"))
async def on_help(c: AndroidRepo, union: Union[Message, CallbackQuery]):
    is_callback = isinstance(union, CallbackQuery)
    m = union.message if is_callback else union

    if m.chat.type == ChatType.PRIVATE:
        keyboard = [
            [
                ("🔧 Utilities", "help_commands"),
                ("💭 Contact", "help_contact"),
                ("📝 Requests", "help_requests"),
            ],
            [
                ("🔙 Back", "start_back"),
            ],
        ]
        text = "Choose a category from the buttons below to get help."
    else:
        keyboard = [
            [
                (
                    "Click here for help!",
                    f"http://t.me/{c.me.username}?start=help",
                    "url",
                )
            ]
        ]
        text = "I am the <b>official bot of the Android Repository channel</b>, click the button below to find out what I can do for you."
    await (m.edit_text if is_callback else m.reply_text)(
        text,
        reply_markup=c.ikb(keyboard),
        disable_web_page_preview=True,
    )


@AndroidRepo.on_message(filters.cmd("about"))
@AndroidRepo.on_callback_query(filters.regex("^about$"))
async def about(c: AndroidRepo, union: Union[Message, CallbackQuery]):
    is_callback = isinstance(union, CallbackQuery)
    m = union.message if is_callback else union

    keyboard = [
        [
            ("📦 GitHub", "https://github.com/AmanoTeam/AndroidRepo", "url"),
            ("📚 Channel", "https://t.me/AndroidRepo", "url"),
        ]
    ]

    if m.chat.type == ChatType.PRIVATE:
        keyboard.append(
            [
                ("🔙 Back", "start_back"),
            ],
        )

    await (m.edit_text if is_callback else m.reply_text)(
        text=(
            (
                "<b>{bot_name}</b> is a bot developed in <i>Python</i> using the Mtproto library <i>Pyrogram</i>, it was made to "
                "be fast and stable in order to help the admins of the @AndroidRepo channel and its members."
                "\n\n<b>Version</b>: {version} (<code>{version_code}</code>)"
            ).format(
                bot_name=c.me.first_name,
                version=f"<a href='https://github.com/AmanoTeam/AndroidRepo/commit/{c.version}'>{c.version}</a>",
                version_code=c.version_code,
            )
        ),
        disable_web_page_preview=True,
        reply_markup=c.ikb(keyboard),
    )


@AndroidRepo.on_callback_query(filters.regex("^help_requests$"))
async def help_requests(c: AndroidRepo, m: CallbackQuery):
    keyboard = [[("🔙 Back", "help")]]
    text = (
        "<b>Here is what I can do for you:</b>\n"
        " - <b>/request (link)</b>: <i>Make requests for files that could be sent on the channel.</i>\n"
        " - <b>/myrequests</b>: <i>See all the requests you have already made.</i>\n"
        " - <b>/cancelrequest (ID)</b>: <i>Cancel the request for the specified ID.</i>\n\n"
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
        " - <b>/contact</b>: <i>Enters contact mode.</i>\n"
        " - <b>/quit</b>: <i>Get out of contact mode.</i>\n\n"
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
        " - <b>/magisk (branch)</b>: <i>Returns the latest version of Magisk in the specified branch.</i>\n"
        " - <b>/lsposed (zygisk or riru)</b>: <i>Returns the latest version of LSPosed.</i>\n"
        " - <b>/twrp (codename)</b>: <i>Gets latest TWRP for the android device using the codename.</i>\n"
        " - <b>/ofox (codename)</b>: <i>Gets latest OFRP for the android device using the codename.</i>\n"
        " - <b>/ofox or /ofox beta</b>: <i>Sends the list of devices with stable or beta releases supported by OFRP.</i>\n"
        "\n<b>Available Magisk branches:</b> <code>stable</code>, <code>beta</code>, <code>canary</code>."
    )
    await m.message.edit_text(
        text,
        reply_markup=c.ikb(keyboard),
        disable_web_page_preview=True,
    )
