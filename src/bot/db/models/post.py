# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column  # noqa: TC002

from bot.db.base import Base
from bot.integrations.repositories import RepositoryPlatform


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[RepositoryPlatform] = mapped_column(Enum(RepositoryPlatform, native_enum=False, length=16))
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    channel_message_id: Mapped[int] = mapped_column(BigInteger)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("platform", "owner", "name", name="uq_posts_platform_owner_name"),)
