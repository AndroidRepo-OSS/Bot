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
from pyrogram.types import Message
from ..database import Contact
from ..config import STAFF_ID


@Client.on_message(filters.private & filters.cmd("contact"))
async def on_contact_m(c: Client, m: Message):
    user = m.from_user
    contact = await Contact.filter(user=user.id)
    if len(contact) > 0:
        return await m.reply_text(
            "You are already in contact mode, you can start talking."
        )
    else:
        await Contact.create(user=user.id)
        await c.send_log_message(f"{user.mention} enter contact mode.")
        return await m.reply_text(
            "You have successfully entered contact mode, everything you send here will be forwarded to the staff group."
        )


@Client.on_message(filters.private & filters.cmd("quit"))
async def on_quit_m(c: Client, m: Message):
    user = m.from_user
    contact = await Contact.filter(user=user.id)
    if len(contact) > 0:
        await contact[0].delete()
        await c.send_log_message(f"{user.mention} left contact mode.")
        return await m.reply_text(
            "You have successfully exited contact mode, I will no longer forward your messages."
        )
    else:
        return await m.reply_text("You are not in contact mode.")


async def is_contact(_, __, m) -> bool:
    user = m.from_user
    if not user:
        return
    return len(await Contact.filter(user=user.id)) > 0


filters.is_contact = filters.create(is_contact, "IsContactFilter")


@Client.on_message(filters.private & filters.is_contact)
async def on_message_m(c: Client, m: Message):
    await c.forward_messages(
        chat_id=STAFF_ID, from_chat_id=m.chat.id, message_ids=m.message_id
    )


@Client.on_message(filters.sudo & filters.chat(STAFF_ID) & filters.reply)
async def on_answer_m(c: Client, m: Message):
    reply = m.reply_to_message
    if reply.forward_from:
        user = reply.forward_from
        contact = await Contact.filter(user=user.id)
        if len(contact) > 0:
            await c.copy_message(
                chat_id=user.id, from_chat_id=m.chat.id, message_id=m.message_id
            )
