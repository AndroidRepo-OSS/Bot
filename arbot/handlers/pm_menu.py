# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2023 Hitalo M. <https://github.com/HitaloM>

import html

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from arbot.filters.chats import ChatTypeFilter
from arbot.utils.callback_data import StartCallback

router = Router(name="pm_menu")


@router.message(CommandStart(), ChatTypeFilter(ChatType.PRIVATE))
@router.callback_query(StartCallback.filter(F.menu == "start"))
async def start_command(union: Message | CallbackQuery):
    is_callback = isinstance(union, CallbackQuery)
    message = union.message if is_callback else union
    if not message or not union.from_user:
        return

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=_("ℹ️ About"), callback_data=StartCallback(menu="about"))
    keyboard.button(text=_("🌐 Language"), callback_data=StartCallback(menu="language"))
    keyboard.button(text=_("👮‍♂️ Help"), callback_data=StartCallback(menu="help"))
    keyboard.adjust(2)

    text = _(
        "Hello, <b>{user_name}</b>. I am the <b>official Android Repository bot</b>, a Telegram \
bot developed to help the admins of the @AndroidRepo channel and its members."
    ).format(user_name=html.escape(union.from_user.full_name))

    await (message.edit_text if is_callback else message.reply)(
        text,
        reply_markup=keyboard.as_markup(),
    )


@router.message(Command("help"), ChatTypeFilter(ChatType.PRIVATE))
@router.callback_query(StartCallback.filter(F.menu == "help"))
async def help(union: Message | CallbackQuery):
    is_callback = isinstance(union, CallbackQuery)
    message = union.message if is_callback else union
    if not message or not union.from_user:
        return

    # keyboard = InlineKeyboardBuilder()
    # keyboard.adjust(3)

    # if is_callback or message.chat.type == ChatType.PRIVATE:
    #     keyboard.row(
    #         InlineKeyboardButton(
    #             text=_("🔙 Back"), callback_data=StartCallback(menu="start").pack()
    #         )
    #     )

    text = _(
        "This is the menu where all my modules are concentrated, click on one of the buttons \
below to start exploring all my functions."
    )

    await (message.edit_text if is_callback else message.reply)(text)


@router.message(Command("about"))
@router.callback_query(StartCallback.filter(F.menu == "about"))
async def about(union: Message | CallbackQuery):
    is_callback = isinstance(union, CallbackQuery)
    message = union.message if is_callback else union
    if not message:
        return

    text = _(
        "AndroidRepo[Bot] is a bot developed in Python using the AIOGram library, it was made to \
be fast and stable in order to help the admins of the @AndroidRepo channel and its members. The \
bot is open source and is available on GitHub, if you want to contribute to the project, just \
click on the button below and join our channel to stay on top of all the news and updates."
    )

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=_("📦 GitHub"), url="https://github.com/AndroidRepo-OSS/Bot")
    keyboard.button(text=_("📚 Channel"), url="https://t.me/HitaloProjects")
    keyboard.adjust(2)

    if is_callback or message.chat.type == ChatType.PRIVATE:
        keyboard.row(
            InlineKeyboardButton(
                text=_("🔙 Back"), callback_data=StartCallback(menu="start").pack()
            )
        )

    await (message.edit_text if is_callback else message.reply)(
        text,
        reply_markup=keyboard.as_markup(),
    )
