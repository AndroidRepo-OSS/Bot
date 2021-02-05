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

import asyncio
import os
import traceback
import sys

from pyrogram import Client, filters
from pyrogram.types import Message
from meval import meval


@Client.on_message(filters.sudo & filters.cmd("restart"))
async def on_restart_m(c: Client, m: Message):
    await m.reply_text("Restarting...")
    args = [sys.executable, "-m", "bot"]
    os.execv(sys.executable, args)


@Client.on_message(filters.sudo & filters.cmd("upgrade"))
async def on_upgrade_m(c: Client, m: Message):
    sm = await m.reply_text("Checking...")
    proc = await asyncio.create_subprocess_shell(
        "git pull --no-edit",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout = (await proc.communicate())[0]
    if proc.returncode == 0:
        if "Already up to date." in stdout.decode():
            await sm.edit_text("There is nothing to update.")
        else:
            await sm.edit_text("Restarting...")
            args = [sys.executable, "-m", "bot"]
            os.execv(sys.executable, args)
    else:
        error = ""
        lines = stdout.decode().split("\n")
        for line in lines:
            error += f"<code>{line}</code>\n"
        await sm.edit_text(
            f"Update failed (process exited with {proc.returncode}):\n{error}"
        )
        proc = await asyncio.create_subprocess_shell("git merge --abort")
        await proc.communicate()


@Client.on_message(filters.sudo & filters.cmd("shutdown"))
async def on_shutdown_m(c: Client, m: Message):
    await m.reply_text("Goodbye...")
    sys.exit()


@Client.on_message(filters.sudo & filters.cmd("term(inal)? "))
async def on_terminal_m(c: Client, m: Message):
    command = m.text.split()[0]
    code = m.text[len(command) + 1 :]
    sm = await m.reply_text("Running...")
    proc = await asyncio.create_subprocess_shell(
        code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout = (await proc.communicate())[0]
    output = ""
    lines = stdout.decode().split("\n")
    for line in lines:
        output += f"<code>{line}</code>\n"
    output_message = f"<b>Input\n&gt;</b> <code>{code}</code>\n\n"
    if len(output) > 0:
        output_message += f"<b>Output\n&gt;</b> {output}"
    await sm.edit_text(output_message)


@Client.on_message(filters.sudo & filters.cmd("ev(al)? "))
async def on_eval_m(c: Client, m: Message):
    command = m.text.split()[0]
    eval_code = m.text[len(command) + 1 :]
    sm = await m.reply_text("Running...")
    try:
        stdout = await meval(eval_code, globals(), **locals())
    except:
        error = traceback.format_exc()
        await sm.edit_text(
            f"An error occurred while running the code:\n<code>{error}</code>"
        )
        return
    output = ""
    lines = str(stdout).split("\n")
    for line in lines:
        output += f"<code>{line}</code>\n"
    output_message = f"<b>Input\n&gt;</b> <code>{eval_code}</code>\n\n"
    if len(output) > 0:
        output_message += f"<b>Output\n&gt;</b> {output}"
    await sm.edit_text(output_message)


@Client.on_message(filters.sudo & filters.cmd("ex(ec(ute)?)? "))
async def on_execute_m(c: Client, m: Message):
    command = m.text.split()[0]
    code = m.text[len(command) + 1 :]
    sm = await m.reply_text("Running...")
    function = f"""
async def _aexec_(c: Client, m: Message):
    """
    for line in code.split("\n"):
        function += f"\n    {line}"
    exec(function)
    try:
        await locals()["_aexec_"](c, m)
    except:
        error = traceback.format_exc()
        await sm.edit_text(
            f"An error occurred while running the code:\n<code>{error}</code>"
        )
        return
    output_message = f"<b>Input\n&gt;</b> <code>{code}</code>\n\n"
    await sm.edit_text(output_message)
