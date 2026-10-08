from dataclasses import dataclass, replace
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.formatting import Bold, Text, as_list
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.db.publications import PublicationCooldown, check_publication_eligibility
from androidrepo_bot.db.repositories import register_repository
from androidrepo_bot.errors import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    GenerationError,
    InsufficientRepositoryEvidenceError,
    MissingDownloadSourceError,
    NotAndroidProjectError,
    RateLimitError,
    RepositoryAccessError,
    RepositoryNotFoundError,
)
from androidrepo_bot.generation.service import generate
from androidrepo_bot.media.banner import render_banner
from androidrepo_bot.media.models import BannerImage, BannerRequest
from androidrepo_bot.posts.state import DraftSession, DraftState
from androidrepo_bot.posts.telegram import deactivate_previous, missing_download_keyboard, send_draft

if TYPE_CHECKING:
    from collections.abc import Mapping

    import aiohttp
    from aiogram import Bot
    from aiogram.types import Message, User
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from androidrepo_bot.admin import AdminLog
    from androidrepo_bot.generation.models import PostDraft
    from androidrepo_bot.generation.service import PostAgent
    from androidrepo_bot.repositories.models import (
        RepositoryClient,
        RepositoryDetails,
        RepositoryProvider,
        RepositoryRef,
    )

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DraftWorkflow:
    providers: Mapping[RepositoryProvider, RepositoryClient]
    bot: Bot
    agent: PostAgent
    http: aiohttp.ClientSession
    sessions: async_sessionmaker[AsyncSession]
    admin_log: AdminLog

    async def _generate(
        self, repository: RepositoryDetails, *, allow_missing_download: bool
    ) -> tuple[PostDraft, BannerImage]:
        draft = await generate(self.agent, repository, allow_missing_download=allow_missing_download)
        banner = await render_banner(
            self.http,
            BannerRequest(
                project_name=draft.title,
                repository=repository.ref.full_name,
                provider=repository.ref.provider.display_name,
                primary_language=repository.languages[0] if repository.languages else None,
                license_name=repository.license,
                release=repository.release.tag if repository.release else None,
                topics=repository.topics[:3],
            ),
        )
        return draft, banner

    async def create(
        self,
        message: Message,
        state: DraftState,
        repository: RepositoryRef,
        *,
        owner: User,
        allow_missing_download: bool = False,
    ) -> DraftSession | None:
        previous = await deactivate_previous(message, state, self.bot)
        if previous is not None:
            await self.admin_log.draft_cancelled(user=owner, session=previous, reason="Replaced by a new /post command")
        started_at = perf_counter()
        try:
            result = await self._create_draft(
                message, state, repository, requested_by_user_id=owner.id, allow_missing_download=allow_missing_download
            )
            if isinstance(result, PublicationCooldown):
                await state.clear()
                await message.answer(**_cooldown_message(result).as_kwargs())
                return None
            session, banner = result
        except (NotAndroidProjectError, InsufficientRepositoryEvidenceError) as error:
            await state.clear()
            title = (
                "Project is not related to Android"
                if isinstance(error, NotAndroidProjectError)
                else "Not enough repository evidence"
            )
            await message.answer(**_error_message(title, str(error)).as_kwargs())
            await self._log_creation_failure(owner, repository, started_at, error)
            return None
        except MissingDownloadSourceError as error:
            await state.clear()
            warning = await message.answer(
                **as_list(
                    as_list(Text("⚠️ ", Bold("No official download source found")), str(error)),
                    "Generate the post without a Download button?",
                    sep="\n\n",
                ).as_kwargs(),
                reply_markup=missing_download_keyboard(),
            )
            try:
                await state.wait_for_download(repository, message_id=warning.message_id, owner_user_id=owner.id)
            except BaseException:
                await state.clear()
                await _delete_message(warning, "Untracked download confirmation remained after state storage failed")
                raise
            return None
        except (RepositoryAccessError, GenerationError, SQLAlchemyError, TelegramAPIError, ValueError) as error:
            await state.clear()
            await message.answer(**_workflow_error_message(error).as_kwargs())
            await self._log_creation_failure(owner, repository, started_at, error)
            return None

        if session.repository.readme is None:
            try:
                notice = await message.answer("⚠️ No README was available, so this draft uses repository metadata only.")
            except TelegramAPIError as error:
                logger.warning("Could not send missing README notice", error_type=type(error).__name__)
            else:
                session = replace(session, notice_message_id=notice.message_id)
                await state.save(session)

        await self.admin_log.draft_created(
            user=owner, session=session, duration_seconds=perf_counter() - started_at, banner_artwork=banner.artwork_id
        )
        return session

    async def revise(self, message: Message, state: DraftState, session: DraftSession) -> bool:
        try:
            await self._replace_draft(message, state, session)
        except (GenerationError, ValueError, TelegramAPIError) as error:
            logger.warning("Could not regenerate the draft", error_type=type(error).__name__)
            await message.answer(
                **as_list(
                    Bold("Could not regenerate the draft"), "The current draft is still available. Try again later."
                ).as_kwargs()
            )
            return False

        await _delete_message(message, "Previous draft remained after successful regeneration")
        return True

    async def _create_draft(
        self,
        message: Message,
        state: DraftState,
        repository: RepositoryRef,
        *,
        requested_by_user_id: int,
        allow_missing_download: bool,
    ) -> tuple[DraftSession, BannerImage] | PublicationCooldown:
        details = await self.providers[repository.provider].fetch(repository)
        registered = await register_repository(self.sessions, details, repository)
        cooldown = await check_publication_eligibility(
            self.sessions, registered, requested_by_user_id=requested_by_user_id
        )
        if not cooldown.allowed:
            return cooldown
        draft, banner = await self._generate(details, allow_missing_download=allow_missing_download)
        draft_message = await send_draft(message, draft, banner)
        session = DraftSession(
            owner_user_id=requested_by_user_id,
            message_id=draft_message.message_id,
            repository=details,
            draft=draft,
            registered_repository=registered,
        )
        try:
            await state.save(session)
        except BaseException:
            await _delete_message(draft_message, "Untracked draft remained after state storage failed")
            raise
        return session, banner

    async def _replace_draft(self, message: Message, state: DraftState, session: DraftSession) -> None:
        draft, banner = await self._generate(
            session.repository, allow_missing_download=session.draft.download_url is None
        )
        replacement = await send_draft(message, draft, banner)
        try:
            await state.save(replace(session, draft=draft, message_id=replacement.message_id))
        except BaseException:
            await _delete_message(replacement, "Untracked revision remained after state storage failed")
            raise

    async def _log_creation_failure(
        self, owner: User, repository: RepositoryRef, started_at: float, error: Exception
    ) -> None:
        await self.admin_log.draft_creation_failed(
            user=owner,
            repository=repository,
            duration_seconds=perf_counter() - started_at,
            error_type=type(error).__name__,
        )


async def _delete_message(message: Message, log_message: str) -> None:
    try:
        await message.delete()
    except TelegramAPIError as error:
        logger.warning(log_message, message_id=message.message_id, error_type=type(error).__name__)


def _cooldown_message(cooldown: PublicationCooldown) -> Text:
    if cooldown.blocked_until is None:
        return as_list(Bold("Publication cooldown"), "This repository was published recently. Try again later.")
    return as_list(
        Bold("Publication cooldown"),
        f"This repository was published recently. Try again after {cooldown.blocked_until:%Y-%m-%d}.",
    )


def _workflow_error_message(error: Exception) -> Text:
    if isinstance(error, RepositoryNotFoundError):
        return _error_message("Repository not found", "Check that the URL is public and spelled correctly.")
    if isinstance(error, RateLimitError):
        return _error_message("Provider rate limit", "Try again later.")
    if isinstance(error, ExternalServiceTimeoutError):
        return _error_message("Provider took too long", "Try again shortly.")
    if isinstance(error, ExternalServiceError):
        return _error_message("Provider temporarily unavailable", "Try again later.")
    return _error_message("Could not create the post draft", "Try again later.")


def _error_message(heading: str, action: str) -> Text:
    return as_list(Bold(heading), action)
