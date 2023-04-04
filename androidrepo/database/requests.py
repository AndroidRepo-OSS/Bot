# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2021-2023 Hitalo M. <https://github.com/HitaloM>

from typing import Dict, Optional

from .core import database

conn = database.get_conn()


async def get_request_by_user_id(user_id: int) -> Optional[Dict]:
    cursor = await conn.execute("SELECT * FROM requests WHERE user = ?", (user_id,))
    row = await cursor.fetchall()
    await cursor.close()
    return None if row is None else row


async def get_request_by_message_id(message_id: int) -> Optional[Dict]:
    cursor = await conn.execute(
        "SELECT * FROM requests WHERE message_id = ?", (message_id,)
    )

    row = await cursor.fetchall()
    await cursor.close()
    return None if row is None else row


async def get_request_by_request_id(request_id: int) -> Optional[Dict]:
    cursor = await conn.execute(
        "SELECT * FROM requests WHERE request_id = ?", (request_id,)
    )

    row = await cursor.fetchall()
    await cursor.close()
    return None if row is None else row


async def create_request(
    user_id: int,
    time: str,
    ignore: int,
    request: str,
    request_id: int,
    attempts: int,
    message_id: int,
) -> None:
    await conn.execute(
        "INSERT INTO requests (user, time, ignore, request, request_id, attempts, message_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, time, ignore, request, request_id, attempts, message_id),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def update_request(
    user_id: int,
    time: str,
    ignore: int,
    request: str,
    request_id: int,
    attempts: int,
    message_id: int,
) -> None:
    await conn.execute(
        "UPDATE requests SET time = ?, ignore = ?, request = ?, attempts = ?, request_id = ?, message_id = ? WHERE user = ?",
        (time, ignore, request, attempts, request_id, message_id, user_id),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def update_request_from_dict(request: int, data: Dict):
    await conn.execute(
        "UPDATE requests SET time = ?, ignore = ?, request = ?, attempts = ?, request_id = ?, message_id = ? WHERE request_id = ?",
        (
            data["time"],
            data["ignore"],
            data["request"],
            data["attempts"],
            data["request_id"],
            data["message_id"],
            request,
        ),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def delete_request(user_id: int, request_id: int) -> None:
    await conn.execute(
        "DELETE FROM requests WHERE user = ? AND request_id = ?", (user_id, request_id)
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()
