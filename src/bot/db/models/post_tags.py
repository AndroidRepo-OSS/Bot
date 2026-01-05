# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from sqlalchemy import JSON, Enum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column  # noqa: TC002

from bot.db.base import Base
from bot.integrations.repositories import RepositoryPlatform


class PostTags(Base):
    __tablename__ = "post_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[RepositoryPlatform] = mapped_column(Enum(RepositoryPlatform, native_enum=False, length=16))
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (UniqueConstraint("platform", "owner", "name", name="uq_post_tags_platform_owner_name"),)
