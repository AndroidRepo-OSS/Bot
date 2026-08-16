from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.formatting import Bold, Code, Text, TextLink, TextMention, as_key_value, as_list

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import User

    from androidrepo_bot.posts.publication import PublicationReceipt
    from androidrepo_bot.posts.state import DraftSession
    from androidrepo_bot.repositories.models import RepositoryRef

logger = structlog.get_logger(__name__)


class AdminLog:
    def __init__(self, *, bot: Bot, chat_id: int, topic_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._topic_id = topic_id

    async def bot_started(self) -> None:
        await self._send(_event("🟢 ", "Bot started", as_key_value("Bot ID", self._bot.id)))

    async def bot_stopped(self) -> None:
        await self._send(_event("⚪ ", "Bot stopped", as_key_value("Bot ID", self._bot.id)))

    async def draft_created(
        self, *, user: User, session: DraftSession, duration_seconds: float, banner_artwork: str
    ) -> None:
        await self._send(
            _event(
                "📝 ",
                "Draft created",
                _repository(session),
                as_key_value("Title", session.draft.title),
                _user(user),
                as_key_value("Draft message ID", session.message_id),
                as_key_value("Generation time", f"{duration_seconds:.1f}s"),
                as_key_value("Banner artwork", banner_artwork),
            )
        )

    async def draft_creation_failed(
        self, *, user: User, repository: RepositoryRef, duration_seconds: float, error_type: str
    ) -> None:
        await self._send(
            _event(
                "⚠️ ",
                "Draft creation failed",
                _repository_ref(repository),
                _user(user),
                as_key_value("Failed after", f"{duration_seconds:.1f}s"),
                as_key_value("Error type", error_type),
            )
        )

    async def post_published(
        self, *, user: User, session: DraftSession, channel_id: int, message_id: int, reconciled: bool = False
    ) -> None:
        await self._send(
            _event(
                "⚠️ " if reconciled else "✅ ",
                "Publication reconciled" if reconciled else "Publication completed",
                _repository(session),
                as_key_value("Title", session.draft.title),
                _user(user),
                as_key_value("Channel ID", channel_id),
                as_key_value("Published message ID", message_id),
            )
        )

    async def publication_failed(self, *, user: User, session: DraftSession, error_type: str) -> None:
        await self._send(
            _event(
                "🚨 ",
                "Publication failed",
                _repository(session),
                as_key_value("Title", session.draft.title),
                _user(user),
                as_key_value("Error type", error_type),
            )
        )

    async def publication_recovery_required(
        self,
        *,
        user: User,
        session: DraftSession,
        operation_id: int,
        error_type: str,
        receipt: PublicationReceipt | None,
    ) -> None:
        details = [as_key_value("Operation ID", operation_id), as_key_value("Error type", error_type)]
        if receipt is not None:
            details.extend((
                as_key_value("Channel ID", receipt.channel_id),
                as_key_value("Channel message ID", receipt.channel_message_id),
                as_key_value("Publication time", receipt.published_at.isoformat()),
                as_key_value(
                    "Recovery command",
                    Code(f"/reconcile {operation_id} {receipt.channel_message_id} {receipt.published_at.isoformat()}"),
                ),
            ))
        else:
            details.extend((
                as_key_value("Absent command", Code(f"/reconcile {operation_id} absent")),
                as_key_value(
                    "Visible command",
                    Code(f"/reconcile {operation_id} <channel-message-id> <ISO-8601-publication-time>"),
                ),
            ))
        await self._send(
            _event(
                "🚨 ",
                "Publication recovery required",
                _repository(session),
                as_key_value("Title", session.draft.title),
                _user(user),
                *details,
            )
        )

    async def draft_cancelled(self, *, user: User, session: DraftSession, reason: str) -> None:
        await self._send(
            _event(
                "🗑️ ",
                "Draft cancelled",
                _repository(session),
                as_key_value("Title", session.draft.title),
                _user(user),
                as_key_value("Reason", reason),
            )
        )

    async def _send(self, content: Text) -> None:
        try:
            await self._bot.send_message(chat_id=self._chat_id, message_thread_id=self._topic_id, **content.as_kwargs())
        except TelegramAPIError as error:
            logger.warning(
                "Could not send admin log to Telegram",
                chat_id=self._chat_id,
                topic_id=self._topic_id,
                error_type=type(error).__name__,
                exc_info=True,
            )


def _event(icon: str, heading: str, *lines: str | Text) -> Text:
    return as_list(Text(icon, Bold(heading)), *lines)


def _repository(session: DraftSession) -> Text:
    return _repository_ref(session.repository.ref)


def _repository_ref(repository: RepositoryRef) -> Text:
    return as_key_value("Repository", TextLink(repository.full_name, url=repository.url))


def _user(user: User) -> Text:
    name = TextMention(user.full_name, user=user)
    username = f" (@{user.username})" if user.username else ""
    return as_key_value("Admin", Text(name, username, f" [ID: {user.id}]"))
