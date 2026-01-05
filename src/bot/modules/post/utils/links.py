# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations


def build_channel_message_link(chat_id: int, message_id: int) -> str:
    numeric_id = abs(chat_id)
    if str(numeric_id).startswith("100"):
        numeric_id = int(str(numeric_id)[3:])
    return f"https://t.me/c/{numeric_id}/{message_id}"
