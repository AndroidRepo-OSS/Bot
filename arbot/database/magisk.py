# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2023 Hitalo M. <https://github.com/HitaloM>


from .base import SqliteConnection


class MagiskModules(SqliteConnection):
    @staticmethod
    async def get_all() -> list | str | None:
        sql = "SELECT * FROM magisk_modules"
        return await MagiskModules._make_request(sql, fetch=True, mult=True) or None
