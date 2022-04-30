"""Android Repository Telegram Bot modules utilities."""
# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import httpx

from androidrepo.utils import httpx_timeout


async def get_changelog(url: str) -> str:
    changelog = ""
    async with httpx.AsyncClient(
        http2=True, timeout=httpx_timeout, follow_redirects=True
    ) as client:
        response = await client.get(url)
        data = response.read()
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
