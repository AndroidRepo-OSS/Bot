# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from typing import Dict, Optional

from .core import database

conn = database.get_conn()


async def get_all_lsposed() -> Dict:
    cursor = await conn.execute("SELECT * FROM lsposed")
    rows = await cursor.fetchall()
    await cursor.close()
    return rows


async def get_lsposed_by_branch(branch: str) -> Optional[Dict]:
    cursor = await conn.execute("SELECT * FROM lsposed WHERE branch = ?", (branch,))
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def create_lsposed(
    branch: str,
    version: str,
    version_code: int,
    link: str,
    changelog: str,
) -> None:
    await conn.execute(
        "INSERT INTO lsposed (branch, version, version_code, link, changelog) VALUES (?, ?, ?, ?, ?)",
        (branch, version, version_code, link, changelog),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def update_lsposed_from_dict(branch: str, data: Dict) -> None:
    await conn.execute(
        "UPDATE lsposed SET version = ?, version_code = ?, link = ?, changelog = ? WHERE branch = ?",
        (
            data["version"],
            data["version_code"],
            data["link"],
            data["changelog"],
            branch,
        ),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()
