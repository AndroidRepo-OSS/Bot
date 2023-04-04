# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2021-2023 Hitalo M. <https://github.com/HitaloM>

import re
from typing import Callable, Union

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from androidrepo.config import PREFIXES


def command_filter(
    command: str,
    flags: int = 0,
    *args,
    **kwargs,
) -> Callable:
    pattern = f"^[{re.escape(''.join(PREFIXES))}]{command}"
    if not pattern.endswith(("$", " ")):
        pattern += r"(?:\s|$)"

    async def func(flt, client: Client, message: Message):
        value = message.text or message.caption

        if bool(message.edit_date):
            return False

        if bool(value):
            command = value.split()[0]
            if "@" in command:
                b = command.split("@")[1]
                if b.lower() == client.me.username.lower():
                    value = (
                        command.split("@")[0]
                        + (" " if len(value.split()) > 1 else "")
                        + " ".join(value.split()[1:])
                    )
                else:
                    return False

            message.matches = list(flt.p.finditer(value)) or None

        return bool(message.matches)

    return filters.create(
        func,
        "CommandHandler",
        p=re.compile(pattern, flags, *args, **kwargs),
    )


async def sudo_filter(_, client, union: Union[CallbackQuery, Message]) -> Callable:
    user = union.from_user
    return client.is_sudoer(user) if user else False


filters.cmd = command_filter
filters.sudo = filters.create(sudo_filter, "SudoFilter")
