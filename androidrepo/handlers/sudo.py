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

import asyncio
import io
import os
import platform
import sys
import traceback
from datetime import datetime
from typing import Dict

import kantex
import pyrogram
import pyromod
from kantex.html import Bold, Code, KanTeXDocument, KeyValueItem, Section, SubSection
from meval import meval
from pyrogram import filters
from pyrogram.types import CallbackQuery, Message

import androidrepo
from androidrepo.database import Modules
from androidrepo.utils import modules

from ..androidrepo import AndroidRepo


@AndroidRepo.on_message(filters.sudo & filters.cmd("ping"))
async def ping(c: AndroidRepo, m: Message):
    first = datetime.now()
    sent = await m.reply_text("<b>Pong!</b>")
    second = datetime.now()
    time = (second - first).microseconds / 1000
    await sent.edit_text(f"<b>Pong!</b> <code>{time}</code>ms")


@AndroidRepo.on_message(filters.sudo & filters.cmd("reboot"))
async def on_restart_m(c: AndroidRepo, m: Message):
    await m.reply_text("Restarting...")
    args = [sys.executable, "-m", "androidrepo"]
    os.execv(sys.executable, args)


@AndroidRepo.on_message(filters.sudo & filters.cmd("upgrade"))
async def on_upgrade_m(c: AndroidRepo, m: Message):
    sm = await m.reply_text("Checking...")
    await (await asyncio.create_subprocess_shell("git fetch origin")).communicate()
    proc = await asyncio.create_subprocess_shell(
        "git log HEAD..origin/main",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout = (await proc.communicate())[0].decode()
    if proc.returncode == 0:
        if len(stdout) > 0:
            changelog = "<b>Changelog</b>:\n"
            commits = parse_commits(stdout)
            for hash, commit in commits.items():
                changelog += f"  - [<code>{hash[:7]}</code>] {commit['title']}\n"
            changelog += f"\n<b>New commits count</b>: <code>{len(commits)}</code>."
            keyboard = [[("🆕 Upgrade", "upgrade")]]
            await sm.edit_text(changelog, reply_markup=c.ikb(keyboard))
        else:
            return await sm.edit_text("There is nothing to update.")
    else:
        error = ""
        lines = stdout.split("\n")
        for line in lines:
            error += f"<code>{line}</code>\n"
        await sm.edit_text(
            f"Update failed (process exited with {proc.returncode}):\n{error}"
        )


def parse_commits(log: str) -> Dict:
    commits = {}
    last_commit = ""
    lines = log.split("\n")
    for line in lines:
        if line.startswith("commit"):
            last_commit = line.split()[1]
            commits[last_commit] = {}
        if len(line) > 0:
            if line.startswith("    "):
                if "title" in commits[last_commit].keys():
                    commits[last_commit]["message"] = line[4:]
                else:
                    commits[last_commit]["title"] = line[4:]
            else:
                if ":" in line:
                    key, value = line.split(": ")
                    commits[last_commit][key] = value
    return commits


@AndroidRepo.on_callback_query(filters.sudo & filters.regex("^upgrade"))
async def on_upgrade_cq(c: AndroidRepo, cq: CallbackQuery):
    await cq.message.edit_text("Upgrading...")
    proc = await asyncio.create_subprocess_shell(
        "git pull --no-edit",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout = (await proc.communicate())[0].decode()
    if proc.returncode == 0:
        await cq.message.edit_text("Restarting...")
        args = [sys.executable, "-m", "androidrepo"]
        os.execv(sys.executable, args)
    else:
        error = ""
        lines = stdout.split("\n")
        for line in lines:
            error += f"<code>{line}</code>\n"
        await cq.message.edit_text(
            f"Update failed (process exited with {proc.returncode}):\n{error}"
        )


@AndroidRepo.on_message(filters.sudo & filters.cmd("shutdown"))
async def on_shutdown_m(c: AndroidRepo, m: Message):
    await m.reply_text("Goodbye...")
    sys.exit()


@AndroidRepo.on_message(filters.sudo & filters.cmd("(sh(eel)?|term(inal)?) "))
async def on_terminal_m(c: AndroidRepo, m: Message):
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
        if len(output) > (4096 - len(output_message)):
            document = io.BytesIO(
                (output.replace("<code>", "").replace("</code>", "")).encode()
            )
            document.name = "output.txt"
            await c.send_document(chat_id=m.chat.id, document=document)
        else:
            output_message += f"<b>Output\n&gt;</b> {output}"
    await sm.edit_text(output_message)


@AndroidRepo.on_message(filters.sudo & filters.cmd("ev(al)? "))
async def on_eval_m(c: AndroidRepo, m: Message):
    command = m.text.split()[0]
    eval_code = m.text[len(command) + 1 :]
    sm = await m.reply_text("Running...")
    try:
        stdout = await meval(eval_code, globals(), **locals())
    except BaseException:
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
        if len(output) > (4096 - len(output_message)):
            document = io.BytesIO(
                (output.replace("<code>", "").replace("</code>", "")).encode()
            )
            document.name = "output.txt"
            await c.send_document(chat_id=m.chat.id, document=document)
        else:
            output_message += f"<b>Output\n&gt;</b> {output}"
    await sm.edit_text(output_message)


@AndroidRepo.on_message(filters.sudo & filters.cmd("ex(ec(ute)?)? "))
async def on_execute_m(c: AndroidRepo, m: Message):
    command = m.text.split()[0]
    code = m.text[len(command) + 1 :]
    sm = await m.reply_text("Running...")
    function = """
async def _aexec_(c: AndroidRepo, m: Message):
    """
    for line in code.split("\n"):
        function += f"\n    {line}"
    exec(function)
    try:
        await locals()["_aexec_"](c, m)
    except BaseException:
        error = traceback.format_exc()
        await sm.edit_text(
            f"An error occurred while running the code:\n<code>{error}</code>"
        )
        return
    output_message = f"<b>Input\n&gt;</b> <code>{code}</code>\n\n"
    await sm.edit_text(output_message)


@AndroidRepo.on_message(filters.sudo & filters.cmd("(info|py)$"))
async def on_info_m(c: AndroidRepo, m: Message):
    magisk_modules = await Modules.all()
    source_url = "git.io/JtVsY"
    doc = KanTeXDocument(
        Section(
            "AndroidRepo Bot",
            SubSection(
                "General",
                KeyValueItem(Bold("Bot"), androidrepo.__version__),
                KeyValueItem(Bold("KanTeX"), kantex.__version__),
                KeyValueItem(Bold("Python"), platform.python_version()),
                KeyValueItem(Bold("Pyrogram"), pyrogram.__version__),
                KeyValueItem(Bold("Pyromod"), pyromod.__version__),
                KeyValueItem(Bold("Source"), source_url),
                KeyValueItem(Bold("System"), c.system_version),
            ),
            SubSection(
                "Magisk", KeyValueItem(Bold("Modules"), Code(len(magisk_modules)))
            ),
        )
    )
    await m.reply_text(doc, disable_web_page_preview=True)


@AndroidRepo.on_message(filters.sudo & filters.cmd("reload"))
async def modules_reload(c: AndroidRepo, m: Message):
    sent = await m.reply_text("<b>Reloading modules...</b>")
    first = datetime.now()
    modules.reload(c)
    second = datetime.now()
    time = (second - first).microseconds / 1000
    await sent.edit_text(f"<b>Modules reloaded in</b> <code>{time}ms</code>!")
