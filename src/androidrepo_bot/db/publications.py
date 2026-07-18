from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Select, func, select, text
from sqlalchemy.dialects.postgresql import Insert, insert

from androidrepo_bot.db.models import PostAttempt, PublishedPost
from androidrepo_bot.posts.models import PublicationCooldown, PublicationRecord, RegisteredRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from sqlalchemy.sql.dml import ReturningInsert


def utc_now() -> datetime:
    return datetime.now(UTC)


async def publication_cooldown(sessions: async_sessionmaker[AsyncSession], repository_id: int) -> PublicationCooldown:
    async with sessions() as session:
        row = (await session.execute(cooldown_query(repository_id))).one_or_none()
    if row is None:
        return PublicationCooldown(allowed=True, blocked_until=None, last_published_at=None)

    published_at, blocked_until, allowed = row.t
    return PublicationCooldown(
        allowed=allowed, blocked_until=None if allowed else blocked_until, last_published_at=published_at
    )


async def record_blocked_attempt(
    sessions: async_sessionmaker[AsyncSession],
    repository: RegisteredRepository,
    cooldown: PublicationCooldown,
    *,
    requested_by_user_id: int,
) -> None:
    if cooldown.allowed or cooldown.blocked_until is None:
        msg = "blocked attempts require a blocking cooldown with an expiration"
        raise ValueError(msg)
    async with sessions.begin() as session:
        await session.execute(
            blocked_attempt_insert(
                repository, cooldown, requested_by_user_id=requested_by_user_id, attempted_at=utc_now()
            )
        )


async def record_publication(sessions: async_sessionmaker[AsyncSession], publication: PublicationRecord) -> bool:
    async with sessions.begin() as session:
        publication_id = (await session.execute(publication_insert(publication))).scalar_one_or_none()
    return publication_id is not None


def cooldown_query(repository_id: int) -> Select[tuple[datetime, datetime, bool]]:
    cooldown_end = PublishedPost.published_at + text("interval '3 months'")
    return (
        select(PublishedPost.published_at, cooldown_end, func.now() >= cooldown_end)
        .where(PublishedPost.repository_app_id == repository_id)
        .order_by(PublishedPost.published_at.desc())
        .limit(1)
    )


def blocked_attempt_insert(
    repository: RegisteredRepository,
    cooldown: PublicationCooldown,
    *,
    requested_by_user_id: int,
    attempted_at: datetime,
) -> Insert:
    return insert(PostAttempt).values(
        repository_app_id=repository.id,
        provider=repository.ref.provider.value,
        namespace=repository.ref.namespace,
        name=repository.ref.name,
        url=repository.ref.url,
        requested_by_user_id=requested_by_user_id,
        attempted_at=attempted_at,
        status="blocked",
        blocked_until=cooldown.blocked_until,
        reason="cooldown",
    )


def publication_insert(publication: PublicationRecord) -> ReturningInsert[tuple[int]]:
    return (
        insert(PublishedPost)
        .values(
            repository_app_id=publication.repository.id,
            title=publication.title,
            tags=list(publication.tags),
            created_by_user_id=publication.created_by_user_id,
            channel_id=publication.channel_id,
            channel_message_id=publication.channel_message_id,
            published_at=publication.published_at,
        )
        .on_conflict_do_nothing(constraint="uq_published_posts_channel_message")
        .returning(PublishedPost.id)
    )
