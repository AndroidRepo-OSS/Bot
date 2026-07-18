from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.formatting import Bold, Text, TextLink

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import User

    from androidrepo_bot.posts.state import DraftSession
    from androidrepo_bot.repositories.models import RepositoryRef

logger = structlog.get_logger(__name__)


class AdminLog:
    def __init__(self, *, bot: Bot, chat_id: int, topic_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.topic_id = topic_id

    async def bot_started(self) -> None:
        await self._send(_event("🟢 ", "Bot started", f"Bot ID: {self.bot.id}"))

    async def bot_stopped(self) -> None:
        await self._send(_event("⚪ ", "Bot stopped", f"Bot ID: {self.bot.id}"))

    async def draft_created(
        self, *, user: User, session: DraftSession, duration_seconds: float, banner_artwork: str
    ) -> None:
        await self._send(
            _event(
                "📝 ",
                "Draft created",
                _repository(session),
                f"Title: {session.draft.title}",
                _user(user),
                f"Draft message ID: {session.message_id}",
                f"Generation time: {duration_seconds:.1f}s",
                f"Banner artwork: {banner_artwork}",
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
                f"Failed after: {duration_seconds:.1f}s",
                f"Error type: {error_type}",
            )
        )

    async def post_published(self, *, user: User, session: DraftSession, channel_id: int, message_id: int) -> None:
        await self._send(
            _event(
                "✅ ",
                "Post published",
                _repository(session),
                f"Title: {session.draft.title}",
                _user(user),
                f"Channel ID: {channel_id}",
                f"Published message ID: {message_id}",
            )
        )

    async def publication_failed(self, *, user: User, session: DraftSession, error_type: str) -> None:
        await self._send(
            _event(
                "🚨 ",
                "Post publication failed",
                _repository(session),
                f"Title: {session.draft.title}",
                _user(user),
                f"Error type: {error_type}",
            )
        )

    async def draft_cancelled(self, *, user: User, session: DraftSession, reason: str) -> None:
        await self._send(
            _event(
                "🗑️ ",
                "Draft cancelled",
                _repository(session),
                f"Title: {session.draft.title}",
                _user(user),
                f"Reason: {reason}",
            )
        )

    async def _send(self, content: Text) -> None:
        try:
            await self.bot.send_message(chat_id=self.chat_id, message_thread_id=self.topic_id, **content.as_kwargs())
        except TelegramAPIError as error:
            logger.warning(
                "Could not send admin log to Telegram",
                chat_id=self.chat_id,
                topic_id=self.topic_id,
                error_type=type(error).__name__,
                exc_info=True,
            )


def _event(icon: str, heading: str, *lines: str | Text) -> Text:
    content: list[str | Text] = [icon, Bold(heading)]
    for line in lines:
        content.extend(("\n", line))
    return Text(*content)


def _repository(session: DraftSession) -> Text:
    return _repository_ref(session.repository.ref)


def _repository_ref(repository: RepositoryRef) -> Text:
    return Text("Repository: ", TextLink(repository.full_name, url=repository.url))


def _user(user: User) -> str:
    username = f" (@{user.username})" if user.username else ""
    return f"Admin: {user.full_name}{username} [ID: {user.id}]"
