# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot.config import Settings


class SudoersFilter(BaseFilter):
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        settings = Settings()  # type: ignore
        user_id = obj.from_user.id if obj.from_user else None
        return user_id in settings.sudoers
