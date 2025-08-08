# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import asyncio
import os
import sys
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InaccessibleMessage, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pydantic import Field

from bot.filters.sudo import SudoersFilter
from bot.utils.logger import LogLevel, get_logger

router = Router(name="updater")
router.message.filter(SudoersFilter())
router.callback_query.filter(SudoersFilter())


class UpdateCallback(CallbackData, prefix="update"):
    action: str = Field(description="Action to perform during update")


async def _run_command(command: list[str], cwd: Path) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()
    return process.returncode or 0, stdout.decode(), stderr.decode()


async def _fetch_updates(project_root: Path, status_message: Message) -> bool:
    await status_message.edit_text("📡 Checking for updates...")

    try:
        async with asyncio.timeout(30):
            returncode, _, stderr = await _run_command(["git", "fetch", "--all"], project_root)
    except TimeoutError:
        await status_message.edit_text("❌ Timeout fetching updates. Please try again.")
        return False

    if returncode != 0:
        await status_message.edit_text(f"❌ Error fetching updates:\n<code>{stderr}</code>")
        return False

    return True


async def _handle_local_changes(project_root: Path, status_message: Message) -> bool:
    try:
        async with asyncio.timeout(10):
            returncode, stdout, stderr = await _run_command(
                ["git", "status", "--porcelain"], project_root
            )
    except TimeoutError:
        await status_message.edit_text("❌ Timeout checking status. Please try again.")
        return False

    if not stdout.strip():
        return True

    await status_message.edit_text("⚠️ There are uncommitted local changes. Stashing changes...")

    try:
        async with asyncio.timeout(10):
            returncode, _, stderr = await _run_command(
                ["git", "stash", "push", "-m", "Auto-stash before update"], project_root
            )
    except TimeoutError:
        await status_message.edit_text("❌ Timeout stashing changes. Please try again.")
        return False

    if returncode != 0:
        await status_message.edit_text(f"❌ Error stashing changes:\n<code>{stderr}</code>")
        return False

    return True


async def _check_pending_commits(project_root: Path, status_message: Message) -> tuple[bool, str]:
    await status_message.edit_text("🔍 Analyzing available updates...")

    try:
        async with asyncio.timeout(30):
            _, commits_stdout, _ = await _run_command(
                ["git", "log", "--oneline", "HEAD..origin/main"], project_root
            )
    except TimeoutError:
        await status_message.edit_text("❌ Timeout checking commits. Please try again.")
        return False, ""

    if not commits_stdout.strip():
        await status_message.edit_text("✅ Bot is already up to date!")
        return True, ""

    commit_lines = commits_stdout.strip().split("\n")
    commits_text = "\n".join(f"• {line}" for line in commit_lines[:10])
    if len(commit_lines) > 10:
        commits_text += f"\n... and {len(commit_lines) - 10} more commits"

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✅ Confirm Update", callback_data=UpdateCallback(action="confirm"))
    keyboard.button(text="❌ Cancel", callback_data=UpdateCallback(action="cancel"))
    keyboard.adjust(2)

    await status_message.edit_text(
        f"📋 <b>Updates available ({len(commit_lines)} commits):</b>\n\n"
        f"<code>{commits_text}</code>\n\n"
        f"Do you want to proceed with the update?",
        reply_markup=keyboard.as_markup(),
    )

    return True, commits_stdout


async def _pull_updates(project_root: Path, status_message: Message) -> bool:
    await status_message.edit_text("⬇️ Downloading updates...")

    try:
        async with asyncio.timeout(60):
            returncode, _, stderr = await _run_command(
                ["git", "pull", "origin", "main"], project_root
            )
    except TimeoutError:
        await status_message.edit_text("❌ Timeout pulling updates. Please try again.")
        return False

    if returncode != 0:
        await status_message.edit_text(f"❌ Error pulling updates:\n<code>{stderr}</code>")
        return False

    return True


async def _install_dependencies(project_root: Path, status_message: Message) -> bool:
    await status_message.edit_text("📦 Installing dependencies...")

    try:
        async with asyncio.timeout(120):
            returncode, _, stderr = await _run_command(["uv", "sync"], project_root)
    except TimeoutError:
        await status_message.edit_text("❌ Timeout installing dependencies. Please try again.")
        return False

    if returncode != 0:
        await status_message.edit_text(
            f"⚠️ Warning: Error installing dependencies:\n<code>{stderr}</code>\n\n"
            "Continuing with restart..."
        )

    return True


@router.callback_query(UpdateCallback.filter(F.action == "cancel"))
async def cancel_update(callback: CallbackQuery, callback_data: UpdateCallback) -> None:
    await callback.answer()
    if callback.message and not isinstance(callback.message, InaccessibleMessage):
        await callback.message.edit_text("❌ Update cancelled.")


@router.callback_query(UpdateCallback.filter(F.action == "confirm"))
async def confirm_update(callback: CallbackQuery, callback_data: UpdateCallback) -> None:
    await callback.answer()

    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return

    status_message = callback.message

    if callback.bot and callback.from_user:
        logger = get_logger(callback.bot)
        await logger.log_user_action(
            user=callback.from_user,
            action_description="Initiated bot update",
            level=LogLevel.WARNING,
        )

    try:
        project_root = Path(__file__).parent.parent.parent.parent

        if not await _handle_local_changes(project_root, status_message):
            return

        if not await _pull_updates(project_root, status_message):
            return

        if not await _install_dependencies(project_root, status_message):
            return

        if callback.bot:
            triggered_by = callback.from_user.full_name if callback.from_user else "Unknown"
            logger = get_logger(callback.bot)
            await logger.log_system_event(
                event_description="Bot updated successfully - restarting",
                level=LogLevel.SUCCESS,
                extra_data={"triggered_by": triggered_by},
            )

        await status_message.edit_text("🔄 Restarting bot...")
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    except Exception as e:
        await status_message.edit_text(f"❌ Unexpected error during update:\n<code>{e!s}</code>")


@router.message(Command("update"))
async def update_bot(message: Message) -> None:
    status_message = await message.answer("🔄 Starting bot update...")

    try:
        project_root = Path(__file__).parent.parent.parent.parent

        if not await _fetch_updates(project_root, status_message):
            return

        success, commits = await _check_pending_commits(project_root, status_message)
        if not success:
            return

        if not commits:
            return

    except Exception as e:
        await status_message.edit_text(f"❌ Unexpected error during update:\n<code>{e!s}</code>")
