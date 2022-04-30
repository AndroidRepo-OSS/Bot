# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from pyrogram import filters
from pyrogram.types import Message

from androidrepo.config import PREFIXES, STAFF_ID
from androidrepo.database.contact import (
    create_contact,
    delete_contact,
    get_contact_by_id,
)

from ..androidrepo import AndroidRepo


@AndroidRepo.on_message(filters.private & filters.cmd("contact"))
async def on_contact_m(c: AndroidRepo, m: Message):
    user = m.from_user
    contact = await get_contact_by_id(user_id=user.id)
    if contact:
        return await m.reply_text(
            "You are already in contact mode, you can start talking."
        )
    await create_contact(user_id=user.id)
    await c.send_log_message(STAFF_ID, f"{user.mention} enter contact mode.")
    return await m.reply_text(
        "You have successfully entered contact mode, everything you send here will be forwarded to the staff group."
    )


@AndroidRepo.on_message(filters.private & filters.cmd("quit"))
async def on_quit_m(c: AndroidRepo, m: Message):
    user = m.from_user
    contact = await get_contact_by_id(user_id=user.id)
    if contact:
        await delete_contact(user_id=contact["user"])
        await c.send_log_message(STAFF_ID, f"{user.mention} left contact mode.")
        return await m.reply_text(
            "You have successfully exited contact mode, I will no longer forward your messages."
        )
    return await m.reply_text("You are not in contact mode.")


async def is_contact(_, __, m) -> bool:
    user = m.from_user
    if not user:
        return False
    contact = await get_contact_by_id(user_id=user.id)
    if contact is None:
        return False
    return len(contact) > 0


filters.is_contact = filters.create(is_contact, "IsContactFilter")


@AndroidRepo.on_message(filters.private & filters.is_contact)
async def on_message_m(c: AndroidRepo, m: Message):
    for prefix in PREFIXES:
        if m.text and m.text.startswith(prefix):
            m.continue_propagation()
    await c.forward_messages(chat_id=STAFF_ID, from_chat_id=m.chat.id, message_ids=m.id)


async def reply_forwarded(_, __, m) -> bool:
    reply = m.reply_to_message
    return bool(reply.forward_from)


filters.reply_forwarded = filters.create(reply_forwarded, "ReplyForwardedFilter")


@AndroidRepo.on_message(
    filters.chat(STAFF_ID) & filters.reply & filters.reply_forwarded
)
async def on_answer_m(c: AndroidRepo, m: Message):
    reply = m.reply_to_message
    user = reply.forward_from
    contact = await get_contact_by_id(user_id=user.id)
    if len(contact) > 0:
        await c.copy_message(chat_id=user.id, from_chat_id=m.chat.id, message_id=m.id)
