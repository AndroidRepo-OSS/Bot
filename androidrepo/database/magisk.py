# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from typing import Dict, Optional

from .core import database

conn = database.get_conn()


async def get_all_magisk() -> Dict:
    cursor = await conn.execute("SELECT * FROM magisk")
    rows = await cursor.fetchall()
    await cursor.close()
    return rows


async def get_magisk_by_branch(branch: str) -> Optional[Dict]:
    cursor = await conn.execute("SELECT * FROM magisk WHERE branch = ?", (branch,))
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def update_magisk_from_dict(branch: str, data: Dict) -> None:
    await conn.execute(
        "UPDATE magisk SET version = ?, version_code = ?, link = ?, note = ?, changelog = ? WHERE branch = ?",
        (
            data["version"],
            data["version_code"],
            data["link"],
            data["note"],
            data["changelog"],
            branch,
        ),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def create_magisk(
    branch: str,
    version: str,
    version_code: int,
    link: str,
    note: str,
    changelog: str,
) -> None:
    await conn.execute(
        "INSERT INTO magisk (branch, version, version_code, link, note, changelog) VALUES (?, ?, ?, ?, ?, ?)",
        (branch, version, version_code, link, note, changelog),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def get_module_by_id(id: str) -> Optional[Dict]:
    cursor = await conn.execute("SELECT * FROM modules WHERE id = ?", (id,))
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def get_all_modules() -> Dict:
    cursor = await conn.execute("SELECT * FROM modules")
    rows = await cursor.fetchall()
    await cursor.close()
    return rows


async def create_module(
    id: str,
    url: str,
    name: str,
    version: str,
    version_code: int,
    last_update: int,
) -> None:
    await conn.execute(
        "INSERT INTO modules (id, url, name, version, version_code, last_update) VALUES (?, ?, ?, ?, ?, ?)",
        (id, url, name, version, version_code, last_update),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def update_module_by_dict(id: str, data: Dict) -> None:
    await conn.execute(
        "UPDATE modules SET name = ?, version = ?, version_code = ?, last_update = ? WHERE id = ?",
        (
            data["name"],
            data["version"],
            data["version_code"],
            data["last_update"],
            id,
        ),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def delete_module(id: str) -> None:
    await conn.execute("DELETE FROM modules WHERE id = ?", (id,))
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()
