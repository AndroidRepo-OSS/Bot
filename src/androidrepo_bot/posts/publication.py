from asyncio import CancelledError, create_task, shield, sleep, timeout
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramServerError
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.db import publications as publication_db
from androidrepo_bot.posts.ui import published_post_keyboard

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from androidrepo_bot.posts.state import DraftSession

logger = structlog.get_logger(__name__)
_RECONCILIATION_ATTEMPTS = 3
_COPY_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    operation_id: int
    channel_id: int
    channel_message_id: int
    published_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationCompleted:
    receipt: PublicationReceipt
    reconciled: bool = False


@dataclass(frozen=True, slots=True)
class PublicationBlocked:
    cooldown: publication_db.PublicationCooldown


@dataclass(frozen=True, slots=True)
class PublicationInProgress:
    operation_id: int


@dataclass(frozen=True, slots=True)
class PublicationCompensated:
    operation_id: int
    error_type: str


@dataclass(frozen=True, slots=True)
class PublicationRecoveryRequired:
    operation_id: int
    error_type: str
    receipt: PublicationReceipt | None = None


type PublicationOutcome = (
    PublicationCompleted
    | PublicationBlocked
    | PublicationInProgress
    | PublicationCompensated
    | PublicationRecoveryRequired
)


class PublicationWorkflow:
    def __init__(self, *, bot: Bot, channel_id: int, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._bot = bot
        self._channel_id = channel_id
        self._sessions = sessions

    async def publish(self, session: DraftSession, *, source_chat_id: int, actor_user_id: int) -> PublicationOutcome:
        reservation = await publication_db.reserve_publication(
            self._sessions,
            publication_db.PublicationIntent(
                repository=session.registered_repository,
                title=session.draft.title,
                tags=tuple(tag.value for tag in session.draft.tags),
                actor_user_id=actor_user_id,
                source_chat_id=source_chat_id,
                source_message_id=session.message_id,
                channel_id=self._channel_id,
            ),
        )
        match reservation:
            case publication_db.BlockedPublication(cooldown):
                return PublicationBlocked(cooldown)
            case publication_db.PublicationInProgress(operation_id):
                return PublicationInProgress(operation_id)
            case publication_db.PublicationNeedsRecovery(operation_id):
                return PublicationRecoveryRequired(operation_id, "UnresolvedPublication")
            case publication_db.ReservedPublication(operation_id):
                return await self._copy_reserved_publication(operation_id, session, source_chat_id=source_chat_id)

    async def reconcile(
        self, operation_id: int, *, channel_message_id: int | None = None, published_at: datetime | None = None
    ) -> PublicationReceipt | None:
        if channel_message_id is None and published_at is None:
            await publication_db.reconcile_absent_publication(self._sessions, operation_id)
            return None
        if channel_message_id is None or published_at is None:
            msg = "a visible Publication requires both its channel message ID and publication time"
            raise ValueError(msg)
        stored = await publication_db.reconcile_visible_publication(
            self._sessions, operation_id, channel_message_id=channel_message_id, published_at=published_at
        )
        return _receipt(stored)

    async def _copy_reserved_publication(
        self, operation_id: int, session: DraftSession, *, source_chat_id: int
    ) -> PublicationOutcome:
        try:
            async with timeout(_COPY_TIMEOUT_SECONDS):
                copied = await self._bot.copy_message(
                    chat_id=self._channel_id,
                    from_chat_id=source_chat_id,
                    message_id=session.message_id,
                    reply_markup=published_post_keyboard(session.draft),
                )
        except (TimeoutError, TelegramNetworkError, TelegramServerError) as error:
            if await self._mark_delivery(operation_id, uncertain=True):
                return PublicationRecoveryRequired(operation_id, type(error).__name__)
            return PublicationRecoveryRequired(operation_id, "PublicationStateUnavailable")
        except TelegramAPIError:
            if not await self._mark_delivery(operation_id, uncertain=False):
                return PublicationRecoveryRequired(operation_id, "PublicationStateUnavailable")
            raise

        published_at = datetime.now(UTC)
        return await self._complete_after_copy(operation_id, copied.message_id, published_at)

    async def _complete_after_copy(
        self, operation_id: int, channel_message_id: int, published_at: datetime
    ) -> PublicationOutcome:
        completion = create_task(
            self._store_or_compensate(operation_id, channel_message_id=channel_message_id, published_at=published_at)
        )
        try:
            return await shield(completion)
        except CancelledError:
            outcome = await completion
            logger.warning(
                "Publication workflow finished while its Telegram update was cancelled",
                operation_id=operation_id,
                outcome_type=type(outcome).__name__,
            )
            raise

    async def _store_or_compensate(
        self, operation_id: int, *, channel_message_id: int, published_at: datetime
    ) -> PublicationOutcome:
        receipt = PublicationReceipt(operation_id, self._channel_id, channel_message_id, published_at)
        storage_error_type = "PublicationPersistenceError"
        try:
            stored = await publication_db.complete_publication(
                self._sessions, operation_id, channel_message_id=channel_message_id, published_at=published_at
            )
        except (SQLAlchemyError, ValueError) as storage_error:
            storage_error_type = type(storage_error).__name__
            logger.warning(
                "Publication record failed after Telegram delivery; preparing compensation",
                operation_id=operation_id,
                channel_message_id=channel_message_id,
                error_type=storage_error_type,
                exc_info=True,
            )
        else:
            return PublicationCompleted(_receipt(stored))

        return await self._compensate(receipt, storage_error_type=storage_error_type)

    async def _compensate(self, receipt: PublicationReceipt, *, storage_error_type: str) -> PublicationOutcome:
        operation_id = receipt.operation_id

        try:
            compensation_started = await publication_db.begin_publication_compensation(
                self._sessions,
                operation_id,
                channel_message_id=receipt.channel_message_id,
                published_at=receipt.published_at,
            )
        except (SQLAlchemyError, ValueError) as compensation_error:
            logger.exception(
                "Could not persist compensation intent; leaving the Publication visible",
                operation_id=operation_id,
                error_type=type(compensation_error).__name__,
            )
            return PublicationRecoveryRequired(operation_id, type(compensation_error).__name__, receipt)
        if not compensation_started:
            return await self._reconcile_visible_publication(receipt)

        reconciliation_error = await self._delete_publication(receipt)
        if reconciliation_error is not None:
            return await self._reconcile_visible_publication(receipt, error=reconciliation_error)

        try:
            await publication_db.finish_publication_compensation(self._sessions, operation_id)
        except (SQLAlchemyError, ValueError) as compensation_error:
            logger.exception(
                "Telegram compensation succeeded but its durable state is unresolved",
                operation_id=operation_id,
                error_type=type(compensation_error).__name__,
            )
            return PublicationRecoveryRequired(operation_id, type(compensation_error).__name__, receipt)
        return PublicationCompensated(operation_id, storage_error_type)

    async def _delete_publication(self, receipt: PublicationReceipt) -> Exception | None:
        try:
            deleted = await self._bot.delete_message(chat_id=self._channel_id, message_id=receipt.channel_message_id)
        except TelegramAPIError as error:
            return error
        if deleted:
            return None
        return RuntimeError("Telegram did not confirm compensating deletion")

    async def _reconcile_visible_publication(
        self, receipt: PublicationReceipt, *, error: Exception | None = None
    ) -> PublicationOutcome:
        if error is not None:
            logger.error(
                "Compensating Telegram deletion failed; reconciling the visible Publication",
                operation_id=receipt.operation_id,
                channel_message_id=receipt.channel_message_id,
                error_type=type(error).__name__,
                exc_info=(type(error), error, error.__traceback__),
            )
        last_error: Exception = error or RuntimeError("Publication reconciliation required")
        for attempt in range(_RECONCILIATION_ATTEMPTS):
            try:
                stored = await publication_db.complete_publication(
                    self._sessions,
                    receipt.operation_id,
                    channel_message_id=receipt.channel_message_id,
                    published_at=receipt.published_at,
                )
            except (SQLAlchemyError, ValueError) as reconciliation_error:
                last_error = reconciliation_error
                logger.exception(
                    "Visible Publication reconciliation failed",
                    operation_id=receipt.operation_id,
                    attempt=attempt + 1,
                    error_type=type(reconciliation_error).__name__,
                )
                if attempt + 1 < _RECONCILIATION_ATTEMPTS:
                    await sleep(0.2 * 2**attempt)
                continue
            return PublicationCompleted(_receipt(stored), reconciled=True)
        return PublicationRecoveryRequired(receipt.operation_id, type(last_error).__name__, receipt)

    async def _mark_delivery(self, operation_id: int, *, uncertain: bool) -> bool:
        transition = publication_db.mark_publication_uncertain if uncertain else publication_db.mark_publication_failed
        try:
            await transition(self._sessions, operation_id)
        except SQLAlchemyError, ValueError:
            logger.exception(
                "Could not persist Telegram delivery outcome", operation_id=operation_id, delivery_uncertain=uncertain
            )
            return False
        return True


def _receipt(stored: publication_db.StoredPublication) -> PublicationReceipt:
    return PublicationReceipt(
        operation_id=stored.operation_id,
        channel_id=stored.channel_id,
        channel_message_id=stored.channel_message_id,
        published_at=stored.published_at,
    )
