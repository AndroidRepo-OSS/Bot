# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

from typing import Dict, Optional

from .core import database

conn = database.get_conn()


async def get_all_quickpic() -> Dict:
    cursor = await conn.execute("SELECT * FROM quickpic")
    rows = await cursor.fetchall()
    await cursor.close()
    return rows


async def get_quickpic_by_branch(branch: str) -> Optional[Dict]:
    cursor = await conn.execute("SELECT * FROM quickpic WHERE branch = ?", (branch,))
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def create_quickpic(
    branch: str,
    version: int,
    link: str,
    changelog: str,
) -> None:
    await conn.execute(
        "INSERT INTO quickpic (branch, version, download_url, changelog) VALUES (?, ?, ?, ?)",
        (branch, version, link, changelog),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()


async def update_quickpic_from_dict(branch: str, data: Dict) -> None:
    await conn.execute(
        "UPDATE quickpic SET version = ?, download_url = ?, changelog = ? WHERE branch = ?",
        (
            data["version"],
            data["link"],
            data["changelog"],
            branch,
        ),
    )
    if conn.total_changes <= 0:
        raise AssertionError
    await conn.commit()
