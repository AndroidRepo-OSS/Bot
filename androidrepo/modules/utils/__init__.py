"""Android Repository Telegram Bot modules utilities."""
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2021-2023 Hitalo M. <https://github.com/HitaloM>

import httpx


async def get_changelog(url: str) -> str:
    changelog = ""
    async with httpx.AsyncClient(
        http2=True, timeout=40, follow_redirects=True
    ) as client:
        response = await client.get(url)
        data = response.read()
        if "Page not found" in data.decode():
            return "Changelog not found."
        lines = data.decode().split("\n")
        latest_version = False
        for line in lines:
            if len(line) < 1:
                continue
            if line.startswith("##"):
                if not latest_version:
                    latest_version = True
                else:
                    break
            else:
                changelog += f"\n{line}"
    return changelog
