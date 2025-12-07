# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.db import AsyncSessionMaker
    from bot.db.base import Base

TModel = TypeVar("TModel", bound="Base")


class BaseRepository[TModel: "Base"]:
    __slots__ = ("_session_maker",)

    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self._session_maker = session_maker

    def _session(self) -> AsyncSession:
        return self._session_maker()
