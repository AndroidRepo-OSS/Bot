from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import Insert, insert

from androidrepo_bot.db.models import PostAttempt, PublicationOperation, PublicationOperationStatus, PublishedPost

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from androidrepo_bot.db.repositories import RegisteredRepository

_PUBLICATION_LOCK_NAMESPACE = 1_095_789_890
_COPY_LEASE = timedelta(minutes=2)
_COPYING: Final = "copying"
_COMPENSATING: Final = "compensating"
_COMPLETED: Final = "completed"
_UNCERTAIN: Final = "uncertain"
_FAILED: Final = "failed"
_ABANDONED: Final = "abandoned"
_OPEN_OPERATION_STATUSES: tuple[PublicationOperationStatus, ...] = (_COPYING, _COMPENSATING, _UNCERTAIN)
type _ReceiptlessStatus = Literal["uncertain", "failed"]


@dataclass(frozen=True, slots=True)
class PublicationCooldown:
    allowed: bool
    blocked_until: datetime | None


@dataclass(frozen=True, slots=True)
class PublicationIntent:
    repository: RegisteredRepository
    title: str
    tags: tuple[str, ...]
    actor_user_id: int
    source_chat_id: int
    source_message_id: int
    channel_id: int


@dataclass(frozen=True, slots=True)
class ReservedPublication:
    operation_id: int


@dataclass(frozen=True, slots=True)
class BlockedPublication:
    cooldown: PublicationCooldown


@dataclass(frozen=True, slots=True)
class PublicationInProgress:
    operation_id: int


@dataclass(frozen=True, slots=True)
class PublicationNeedsRecovery:
    operation_id: int


@dataclass(frozen=True, slots=True)
class StoredPublication:
    operation_id: int
    channel_id: int
    channel_message_id: int
    published_at: datetime


type PublicationReservation = (
    ReservedPublication | BlockedPublication | PublicationInProgress | PublicationNeedsRecovery
)


async def check_publication_eligibility(
    sessions: async_sessionmaker[AsyncSession], repository: RegisteredRepository, *, requested_by_user_id: int
) -> PublicationCooldown:
    async with sessions.begin() as session:
        cooldown = await _publication_cooldown(session, repository.id)
        if not cooldown.allowed:
            await session.execute(
                _blocked_attempt_insert(
                    repository, cooldown, requested_by_user_id=requested_by_user_id, attempted_at=datetime.now(UTC)
                )
            )
        return cooldown


async def reserve_publication(
    sessions: async_sessionmaker[AsyncSession], intent: PublicationIntent
) -> PublicationReservation:
    async with sessions.begin() as session:
        await _lock_repository(session, intent.repository.id)
        now = await _database_time(session)
        operation = await session.scalar(
            select(PublicationOperation)
            .where(
                PublicationOperation.repository_app_id == intent.repository.id,
                PublicationOperation.status.in_(_OPEN_OPERATION_STATUSES),
            )
            .with_for_update()
        )
        if operation is not None:
            return await _open_operation_reservation(session, operation, now)

        cooldown = await _publication_cooldown(session, intent.repository.id)
        if not cooldown.allowed:
            await session.execute(
                _blocked_attempt_insert(
                    intent.repository, cooldown, requested_by_user_id=intent.actor_user_id, attempted_at=now
                )
            )
            return BlockedPublication(cooldown)

        operation_id = (
            await session.execute(
                insert(PublicationOperation)
                .values(
                    repository_app_id=intent.repository.id,
                    source_chat_id=intent.source_chat_id,
                    source_message_id=intent.source_message_id,
                    channel_id=intent.channel_id,
                    actor_user_id=intent.actor_user_id,
                    title=intent.title,
                    tags=list(intent.tags),
                    status=_COPYING,
                    lease_expires_at=now + _COPY_LEASE,
                    created_at=now,
                    updated_at=now,
                )
                .returning(PublicationOperation.id)
            )
        ).scalar_one()
        return ReservedPublication(operation_id)


async def _open_operation_reservation(
    session: AsyncSession, operation: PublicationOperation, now: datetime
) -> PublicationReservation:
    if operation.status != _COPYING:
        return PublicationNeedsRecovery(operation.id)
    if operation.lease_expires_at is not None and operation.lease_expires_at > now:
        return PublicationInProgress(operation.id)
    await _set_without_receipt(session, operation.id, _UNCERTAIN, now)
    return PublicationNeedsRecovery(operation.id)


async def complete_publication(
    sessions: async_sessionmaker[AsyncSession], operation_id: int, *, channel_message_id: int, published_at: datetime
) -> StoredPublication:
    async with sessions.begin() as session:
        operation = await _locked_operation(session, operation_id)
        await _require_active_workflow(session, operation)
        return await _complete_operation(
            session, operation, channel_message_id=channel_message_id, published_at=published_at
        )


async def reconcile_visible_publication(
    sessions: async_sessionmaker[AsyncSession], operation_id: int, *, channel_message_id: int, published_at: datetime
) -> StoredPublication:
    async with sessions.begin() as session:
        operation = await _locked_operation(session, operation_id)
        await _require_reconcilable(session, operation)
        return await _complete_operation(
            session, operation, channel_message_id=channel_message_id, published_at=published_at
        )


async def begin_publication_compensation(
    sessions: async_sessionmaker[AsyncSession], operation_id: int, *, channel_message_id: int, published_at: datetime
) -> bool:
    async with sessions.begin() as session:
        operation = await _locked_operation(session, operation_id)
        if operation.status == _COMPLETED:
            return False
        if operation.status == _COMPENSATING:
            _receipt_values(operation, expected_message_id=channel_message_id)
            return True
        await _require_active_workflow(session, operation)
        await session.execute(
            update(PublicationOperation)
            .where(PublicationOperation.id == operation_id)
            .values(
                status=_COMPENSATING,
                lease_expires_at=None,
                channel_message_id=channel_message_id,
                published_at=published_at,
                updated_at=func.now(),
            )
        )
        return True


async def finish_publication_compensation(sessions: async_sessionmaker[AsyncSession], operation_id: int) -> None:
    async with sessions.begin() as session:
        operation = await _locked_operation(session, operation_id)
        if operation.status == _ABANDONED:
            return
        if operation.status != _COMPENSATING:
            msg = f"cannot finish compensation for a {operation.status} publication operation"
            raise ValueError(msg)
        await session.execute(
            update(PublicationOperation)
            .where(PublicationOperation.id == operation_id)
            .values(status=_ABANDONED, updated_at=func.now())
        )


async def mark_publication_uncertain(sessions: async_sessionmaker[AsyncSession], operation_id: int) -> None:
    await _close_without_receipt(sessions, operation_id, _UNCERTAIN)


async def mark_publication_failed(sessions: async_sessionmaker[AsyncSession], operation_id: int) -> None:
    await _close_without_receipt(sessions, operation_id, _FAILED)


async def reconcile_absent_publication(sessions: async_sessionmaker[AsyncSession], operation_id: int) -> None:
    async with sessions.begin() as session:
        operation = await _locked_operation(session, operation_id)
        await _require_reconcilable(session, operation)
        if operation.status == _COMPLETED:
            msg = "a completed Publication cannot be reconciled as absent"
            raise ValueError(msg)
        if operation.status in {_FAILED, _ABANDONED}:
            return
        values: dict[str, object] = {"status": _ABANDONED, "lease_expires_at": None, "updated_at": func.now()}
        if operation.status != _COMPENSATING:
            values.update(channel_message_id=None, published_at=None)
        await session.execute(
            update(PublicationOperation).where(PublicationOperation.id == operation_id).values(**values)
        )


async def _complete_operation(
    session: AsyncSession, operation: PublicationOperation, *, channel_message_id: int, published_at: datetime
) -> StoredPublication:
    if operation.status == _COMPLETED:
        return _stored_publication(operation, expected_message_id=channel_message_id)
    if operation.status not in {_COPYING, _COMPENSATING, _UNCERTAIN}:
        msg = f"cannot complete a {operation.status} publication operation"
        raise ValueError(msg)
    if operation.status == _COMPENSATING:
        _, published_at = _receipt_values(operation, expected_message_id=channel_message_id)

    publication_id = await _insert_publication(
        session, operation, channel_message_id=channel_message_id, published_at=published_at
    )
    await session.execute(
        update(PublicationOperation)
        .where(PublicationOperation.id == operation.id)
        .values(
            status=_COMPLETED,
            lease_expires_at=None,
            channel_message_id=channel_message_id,
            published_at=published_at,
            published_post_id=publication_id,
            updated_at=func.now(),
        )
    )
    return StoredPublication(operation.id, operation.channel_id, channel_message_id, published_at)


async def _require_reconcilable(session: AsyncSession, operation: PublicationOperation) -> None:
    if (
        operation.status == _COPYING
        and operation.lease_expires_at is not None
        and operation.lease_expires_at > await _database_time(session)
    ):
        msg = "publication operation is still in progress"
        raise ValueError(msg)


async def _require_active_workflow(session: AsyncSession, operation: PublicationOperation) -> None:
    if operation.status in {_COMPLETED, _COMPENSATING}:
        return
    if (
        operation.status != _COPYING
        or operation.lease_expires_at is None
        or operation.lease_expires_at <= await _database_time(session)
    ):
        msg = f"publication workflow no longer owns a {operation.status} operation"
        raise ValueError(msg)


async def _close_without_receipt(
    sessions: async_sessionmaker[AsyncSession], operation_id: int, status: _ReceiptlessStatus
) -> None:
    async with sessions.begin() as session:
        operation = await _locked_operation(session, operation_id)
        if operation.status == status:
            return
        if operation.status != _COPYING:
            msg = f"cannot mark a {operation.status} publication operation as {status}"
            raise ValueError(msg)
        await _set_without_receipt(session, operation_id, status, await _database_time(session))


async def _insert_publication(
    session: AsyncSession, operation: PublicationOperation, *, channel_message_id: int, published_at: datetime
) -> int:
    publication_id = (
        await session.execute(
            insert(PublishedPost)
            .values(
                repository_app_id=operation.repository_app_id,
                title=operation.title,
                tags=operation.tags,
                created_by_user_id=operation.actor_user_id,
                channel_id=operation.channel_id,
                channel_message_id=channel_message_id,
                published_at=published_at,
            )
            .on_conflict_do_nothing(constraint="uq_published_posts_channel_message")
            .returning(PublishedPost.id)
        )
    ).scalar_one_or_none()
    if publication_id is not None:
        return publication_id
    existing = (
        await session.execute(
            select(PublishedPost.id, PublishedPost.repository_app_id).where(
                PublishedPost.channel_id == operation.channel_id, PublishedPost.channel_message_id == channel_message_id
            )
        )
    ).one()
    publication_id, repository_id = existing.t
    if repository_id != operation.repository_app_id:
        msg = "channel message is already recorded for another repository"
        raise ValueError(msg)
    return publication_id


def _stored_publication(operation: PublicationOperation, *, expected_message_id: int) -> StoredPublication:
    channel_message_id, published_at = _receipt_values(operation, expected_message_id=expected_message_id)
    return StoredPublication(operation.id, operation.channel_id, channel_message_id, published_at)


def _receipt_values(operation: PublicationOperation, *, expected_message_id: int) -> tuple[int, datetime]:
    if operation.channel_message_id is None or operation.published_at is None:
        msg = f"{operation.status} publication operation has no receipt"
        raise ValueError(msg)
    if operation.channel_message_id != expected_message_id:
        msg = "publication operation is associated with another channel message"
        raise ValueError(msg)
    return operation.channel_message_id, operation.published_at


async def _locked_operation(session: AsyncSession, operation_id: int) -> PublicationOperation:
    repository_id = await session.scalar(
        select(PublicationOperation.repository_app_id).where(PublicationOperation.id == operation_id)
    )
    if repository_id is None:
        msg = "publication operation does not exist"
        raise ValueError(msg)
    await _lock_repository(session, repository_id)
    operation = await session.scalar(
        select(PublicationOperation).where(PublicationOperation.id == operation_id).with_for_update()
    )
    if operation is None:
        msg = "publication operation does not exist"
        raise ValueError(msg)
    return operation


async def _lock_repository(session: AsyncSession, repository_id: int) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :repository_id)"),
        {"namespace": _PUBLICATION_LOCK_NAMESPACE, "repository_id": repository_id},
    )


async def _database_time(session: AsyncSession) -> datetime:
    now = await session.scalar(select(func.now()))
    if now is None:
        msg = "PostgreSQL did not provide its current time"
        raise RuntimeError(msg)
    return now


async def _publication_cooldown(session: AsyncSession, repository_id: int) -> PublicationCooldown:
    cooldown_end = PublishedPost.published_at + text("interval '3 months'")
    row = (
        await session.execute(
            select(cooldown_end, func.now() >= cooldown_end)
            .where(PublishedPost.repository_app_id == repository_id)
            .order_by(PublishedPost.published_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return PublicationCooldown(allowed=True, blocked_until=None)
    blocked_until, allowed = row.t
    return PublicationCooldown(allowed=allowed, blocked_until=None if allowed else blocked_until)


def _blocked_attempt_insert(
    repository: RegisteredRepository,
    cooldown: PublicationCooldown,
    *,
    requested_by_user_id: int,
    attempted_at: datetime,
) -> Insert:
    if cooldown.allowed or cooldown.blocked_until is None:
        msg = "blocked attempts require a blocking cooldown with an expiration"
        raise ValueError(msg)
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


async def _set_without_receipt(
    session: AsyncSession, operation_id: int, status: _ReceiptlessStatus, updated_at: datetime
) -> None:
    await session.execute(
        update(PublicationOperation)
        .where(PublicationOperation.id == operation_id)
        .values(
            status=status,
            lease_expires_at=None,
            channel_message_id=None,
            published_at=None,
            published_post_id=None,
            updated_at=updated_at,
        )
    )
