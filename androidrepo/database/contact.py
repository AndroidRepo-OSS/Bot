# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from typing import Dict, Optional

from .core import database

conn = database.get_conn()


async def get_contact_by_id(user_id: int) -> Optional[Dict]:
    cursor = await conn.execute("SELECT * FROM contact WHERE user = ?", (user_id,))
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def create_contact(user_id: int) -> None:
    await conn.execute("INSERT INTO contact (user) VALUES (?)", (user_id,))
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def delete_contact(user_id: int) -> None:
    await conn.execute("DELETE FROM contact WHERE user = ?", (user_id,))
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()
