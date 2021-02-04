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

import os
import sys
import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message


@Client.on_message(filters.sudo & filters.cmd("restart"))
async def on_restart_m(c: Client, m: Message):
    await m.reply_text("Reiniciando...")
    args = [sys.executable, "-m", "bot"]
    os.execv(sys.executable, args)


@Client.on_message(filters.sudo & filters.cmd("upgrade"))
async def on_upgrade_m(c: Client, m: Message):
    sm = await m.reply_text("Verificando...")
    proc = await asyncio.create_subprocess_shell(
        "git pull --no-edit",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout = (await proc.communicate())[0]
    if proc.returncode == 0:
        if "Already up to date." in stdout.decode():
            await sm.edit_text("Não há nada para atualizar.")
        else:
            await sm.edit_text("Reiniciando...")
            args = [sys.executable, "-m", "bot"]
            os.execv(sys.executable, args)
    else:
        error = ''
        lines = stdout.decode().split("\n")
        for line in lines:
            error += f"<code>{line}</code>\n"
        await sm.edit_text(
            f"Atualização falhou (process exited with {proc.returncode}):\n{error}"
        )
        proc = await asyncio.create_subprocess_shell("git merge --abort")
        await proc.communicate()


@Client.on_message(filters.sudo & filters.cmd("shutdown"))
async def on_shutdown_m(c: Client, m: Message):
    await m.reply_text("Adeus...")
    sys.exit()
    
    
@Client.on_message(filters.sudo & filters.cmd("term(inal)? "))
async def on_term_m(c: Client, m: Message):
    command = m.text.split()[0]
    code = m.text[len(command)+1:]
    sm = await m.reply_text("Executando...")
    proc = await asyncio.create_subprocess_shell(
        code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout = (await proc.communicate())[0]
    output = ''
    lines = stdout.decode().split("\n")
    for line in lines:
        output += f"<code>{line}</code>\n"
    output_message = f"<b>Entrada\n&gt;</b> <code>{code}</code>\n\n"
    output_message += f"<b>Saída\n&gt;</b> {output}"
    await sm.edit_text(output_message)