# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from typing import Union

import httpx
import xmltodict
from pyrogram import filters
from pyrogram.types import CallbackQuery, Message

from androidrepo.bot import AndroidRepo


@AndroidRepo.on_callback_query(filters.regex(r"^microg (\w+) (\d+)"))
async def on_microg(c: AndroidRepo, q: CallbackQuery):
    app = q.matches[0].group(1)
    user_id = int(q.matches[0].group(2))

    if q.from_user.id != user_id:
        await q.answer("This button is not for you.", cache_time=60)
        return

    if app == "vending":
        app_id = "com.android.vending"
    if app == "droidguard":
        app_id = "org.microg.gms.droidguard"
    if app == "gms":
        app_id = "com.google.android.gms"
    if app == "gsf":
        app_id = "com.google.android.gsf"

    async with httpx.AsyncClient(http2=True) as client:
        response = await client.get("https://microg.org/fdroid/repo/index.xml")
        data = xmltodict.parse(response.text)

    fdroid = data["fdroid"]
    for app in fdroid["application"]:
        if app["id"] == app_id:
            try:
                package = app["package"][0]
            except KeyError:
                package = app["package"]

            text = f"<b>{app['name']} v{package['version']} ({package['versioncode']})</b>\n"
            text += f"<b>Package:</b> <code>{app['id']}</code>\n"
            text += f"<b>Description:</b> <i>{app['desc']}</i>\n"
            text += f"<b>Updated:</b> {app['lastupdated']}"

    dl_url = f"https://microg.org/fdroid/repo/{package['apkname']}"
    keyboard = [
        [
            ("Download", dl_url, "url"),
            ("GitHub", app["source"], "url"),
        ],
        [("Back", "microg")],
    ]

    await q.edit_message_text(text, reply_markup=c.ikb(keyboard))


@AndroidRepo.on_message(filters.cmd("microg"))
@AndroidRepo.on_callback_query(filters.regex(r"^microg$"))
async def microg_menu(c: AndroidRepo, u: Union[Message, CallbackQuery]):
    is_callback = isinstance(u, CallbackQuery)
    union = u.message if is_callback else u

    user_id = u.from_user.id

    keyboard = [
        [
            ("FakeStore", f"microg vending {user_id}"),
            ("microG DroidGuard Helper", f"microg droidguard {user_id}"),
        ],
        [
            ("microG Services Core", f"microg gms {user_id}"),
            ("microG Services Framework Proxy", f"microg gsf {user_id}"),
        ],
    ]

    text = "<b>microG Project</b>\n"
    text += "<i>A free-as-in-freedom re-implementation of Google's proprietary Android user space apps and libraries.</i>"

    await (union.edit_text if is_callback else union.reply_text)(
        text, reply_markup=c.ikb(keyboard)
    )
