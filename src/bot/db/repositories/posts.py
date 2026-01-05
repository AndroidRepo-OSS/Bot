# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from bot.db.models import Post, PostTags

from .base import BaseRepository

if TYPE_CHECKING:
    from sqlalchemy import Select

    from bot.db import AsyncSessionMaker
    from bot.integrations.repositories import RepositoryPlatform


class PostsRepository(BaseRepository[Post]):
    __slots__ = ()

    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        super().__init__(session_maker)

    async def is_posted(self, *, platform: RepositoryPlatform, owner: str, name: str) -> bool:
        async with self._session_maker() as session:
            stmt = self._base_select(platform=platform, owner=owner, name=name).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def record_post(
        self, *, platform: RepositoryPlatform, owner: str, name: str, channel_message_id: int
    ) -> Post:
        async with self._session_maker() as session:
            result = await session.execute(self._base_select(platform=platform, owner=owner, name=name).limit(1))
            post = result.scalar_one_or_none()
            now = datetime.now(UTC)

            if post:
                post.channel_message_id = channel_message_id
                post.posted_at = now
            else:
                post = Post(
                    platform=platform, owner=owner, name=name, channel_message_id=channel_message_id, posted_at=now
                )
                session.add(post)

            await session.commit()
            await session.refresh(post)
            return post

    async def get_recent_post(
        self, *, platform: RepositoryPlatform, owner: str, name: str, months: int = 3
    ) -> Post | None:
        cutoff = datetime.now(UTC) - timedelta(days=months * 30)
        async with self._session_maker() as session:
            stmt = self._base_select(platform=platform, owner=owner, name=name).where(Post.posted_at >= cutoff).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_tags(self, *, platform: RepositoryPlatform, owner: str, name: str) -> list[str]:
        async with self._session_maker() as session:
            stmt = select(PostTags.tags).where(
                PostTags.platform == platform, PostTags.owner == owner, PostTags.name == name
            )
            result = await session.execute(stmt.limit(1))
            tags = result.scalar_one_or_none() or []

        if not tags:
            return []

        seen: set[str] = set()
        unique_tags: list[str] = []

        for tag in tags:
            if not isinstance(tag, str):
                continue

            cleaned = tag.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                unique_tags.append(cleaned)

        return unique_tags

    async def upsert_tags(self, *, platform: RepositoryPlatform, owner: str, name: str, tags: list[str]) -> None:
        seen: set[str] = set()
        unique_tags: list[str] = []

        for tag in tags:
            if not isinstance(tag, str):
                continue

            cleaned = tag.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                unique_tags.append(cleaned)

        if not unique_tags:
            return

        async with self._session_maker() as session:
            stmt = select(PostTags).where(PostTags.platform == platform, PostTags.owner == owner, PostTags.name == name)
            result = await session.execute(stmt.limit(1))
            record = result.scalar_one_or_none()

            if record:
                record.tags = unique_tags
            else:
                session.add(PostTags(platform=platform, owner=owner, name=name, tags=unique_tags))

            await session.commit()

    @staticmethod
    def _base_select(*, platform: RepositoryPlatform, owner: str, name: str) -> Select[tuple[Post]]:
        return select(Post).where(Post.platform == platform, Post.owner == owner, Post.name == name)
