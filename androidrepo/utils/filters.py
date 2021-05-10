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

import re
from typing import Callable, Union

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from androidrepo.config import PREFIXES


def load(client):
    def command_filter(
        command: str,
        flags: int = 0,
        *args,
        **kwargs,
    ) -> Callable:
        pattern = r"^" + f"[{re.escape(''.join(PREFIXES))}]" + command
        if not pattern.endswith(("$", " ")):
            pattern += r"(?:\s|$)"

        async def func(flt, client: Client, message: Message):
            value = message.text or message.caption

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
        if not user:
            return False
        return client.is_sudoer(user)

    filters.cmd = command_filter
    filters.sudo = filters.create(sudo_filter, "SudoFilter")
