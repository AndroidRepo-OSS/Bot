from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.formatting import Bold, Text, as_list
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.db.publications import check_publication_eligibility
from androidrepo_bot.db.repositories import register_repository
from androidrepo_bot.errors import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    GenerationError,
    MissingDownloadSourceError,
    NotAndroidProjectError,
    RateLimitError,
    RepositoryAccessError,
    RepositoryNotFoundError,
)
from androidrepo_bot.media.banner import render_banner
from androidrepo_bot.media.models import BannerImage, BannerRequest
from androidrepo_bot.posts.models import CooldownBlockedError, PostDraft, PublicationCooldown
from androidrepo_bot.posts.telegram import bound_bot, deactivate_previous
from androidrepo_bot.posts.ui import draft_keyboard, missing_download_keyboard, render_post_media

if TYPE_CHECKING:
    from collections.abc import Mapping

    import aiohttp
    from aiogram.types import Message, User
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from androidrepo_bot.admin import AdminLog
    from androidrepo_bot.generation.service import GenerationService
    from androidrepo_bot.posts.models import RegisteredRepository
    from androidrepo_bot.posts.state import DraftSession, DraftState
    from androidrepo_bot.repositories.models import (
        RepositoryClient,
        RepositoryDetails,
        RepositoryProvider,
        RepositoryRef,
    )

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedDraft:
    repository: RepositoryDetails
    registered_repository: RegisteredRepository
    draft: PostDraft
    banner: BannerImage


class DraftWorkflow:
    def __init__(
        self,
        *,
        providers: Mapping[RepositoryProvider, RepositoryClient],
        generation: GenerationService,
        http: aiohttp.ClientSession,
        sessions: async_sessionmaker[AsyncSession],
        admin_log: AdminLog,
    ) -> None:
        self._providers = dict(providers)
        self._generation = generation
        self._http = http
        self._sessions = sessions
        self._admin_log = admin_log

    async def create(
        self,
        message: Message,
        state: DraftState,
        repository: RepositoryRef,
        *,
        owner: User,
        allow_missing_download: bool = False,
    ) -> DraftSession | None:
        previous = await deactivate_previous(message, state, bound_bot(message))
        if previous is not None:
            await self._admin_log.draft_cancelled(
                user=owner, session=previous, reason="Replaced by a new /post command"
            )
        started_at = perf_counter()
        try:
            prepared, session = await self._create_draft(
                message, state, repository, requested_by_user_id=owner.id, allow_missing_download=allow_missing_download
            )
        except NotAndroidProjectError as error:
            await state.clear()
            await message.answer(**_error_message("Project is not related to Android", str(error)).as_kwargs())
            await self._log_creation_failure(owner, repository, started_at, error)
            return None
        except MissingDownloadSourceError as error:
            await state.wait_for_download(repository)
            try:
                await message.answer(
                    **as_list(
                        as_list(Text("⚠️ ", Bold("No official download source found")), str(error)),
                        "Generate the post without a Download button?",
                        sep="\n\n",
                    ).as_kwargs(),
                    reply_markup=missing_download_keyboard(),
                )
            except TelegramAPIError:
                await state.clear()
                raise
            return None
        except CooldownBlockedError as error:
            await state.clear()
            await message.answer(**_cooldown_message(error.cooldown).as_kwargs())
            return None
        except (RepositoryAccessError, GenerationError, SQLAlchemyError, TelegramAPIError, ValueError) as error:
            await state.clear()
            await message.answer(**_workflow_error_message(error).as_kwargs())
            await self._log_creation_failure(owner, repository, started_at, error)
            return None

        if prepared.repository.readme is None:
            try:
                notice = await message.answer("⚠️ No README was available, so this draft uses repository metadata only.")
            except TelegramAPIError:
                logger.warning("Could not send missing README notice", exc_info=True)
            else:
                session = session.with_notice(notice.message_id)
                await state.save(session)

        await self._admin_log.draft_created(
            user=owner,
            session=session,
            duration_seconds=perf_counter() - started_at,
            banner_artwork=prepared.banner.artwork_id,
        )
        return session

    async def revise(self, message: Message, state: DraftState, session: DraftSession) -> bool:
        try:
            await self._replace_draft(message, state, session)
        except GenerationError, ValueError, TelegramAPIError:
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
    ) -> tuple[PreparedDraft, DraftSession]:
        prepared = await self._prepare_new(
            repository, requested_by_user_id=requested_by_user_id, allow_missing_download=allow_missing_download
        )
        draft_message = await _send_draft(message, prepared.draft, prepared.banner)
        try:
            session = await state.begin(prepared, message_id=draft_message.message_id)
        except BaseException:
            await _delete_message(draft_message, "Untracked draft remained after state storage failed")
            raise
        return prepared, session

    async def _replace_draft(self, message: Message, state: DraftState, session: DraftSession) -> None:
        draft = await self._generation.generate(
            session.repository, allow_missing_download=session.draft.download_url is None
        )
        banner = await self._render_banner(draft, session.repository)
        replacement = await _send_draft(message, draft, banner)
        try:
            await state.save(session.revised(draft, message_id=replacement.message_id))
        except BaseException:
            await _delete_message(replacement, "Untracked revision remained after state storage failed")
            raise

    async def _prepare_new(
        self, repository: RepositoryRef, *, requested_by_user_id: int, allow_missing_download: bool
    ) -> PreparedDraft:
        details = await self._providers[repository.provider].fetch(repository)

        registered = await register_repository(self._sessions, details, repository)
        cooldown = await check_publication_eligibility(
            self._sessions, registered, requested_by_user_id=requested_by_user_id
        )
        if not cooldown.allowed:
            raise CooldownBlockedError(cooldown)

        draft = await self._generation.generate(details, allow_missing_download=allow_missing_download)
        banner = await self._render_banner(draft, details)
        return PreparedDraft(details, registered, draft, banner)

    async def _render_banner(self, draft: PostDraft, repository: RepositoryDetails) -> BannerImage:
        return await render_banner(
            self._http,
            BannerRequest(
                project_name=draft.title,
                repository=repository.ref.full_name,
                provider=repository.ref.provider.display_name,
                primary_language=(repository.languages[0] if repository.languages else None),
                license_name=repository.license,
                release=(repository.release.tag if repository.release is not None else None),
                topics=repository.topics[:3],
            ),
        )

    async def _log_creation_failure(
        self, owner: User, repository: RepositoryRef, started_at: float, error: Exception
    ) -> None:
        await self._admin_log.draft_creation_failed(
            user=owner,
            repository=repository,
            duration_seconds=perf_counter() - started_at,
            error_type=type(error).__name__,
        )


async def _delete_message(message: Message, log_message: str) -> None:
    try:
        await message.delete()
    except TelegramAPIError:
        logger.debug(log_message, message_id=message.message_id, exc_info=True)


async def _send_draft(message: Message, draft: PostDraft, banner: BannerImage) -> Message:
    media = render_post_media(draft, banner)
    return await message.answer_photo(
        photo=media.media,
        caption=media.caption,
        caption_entities=media.caption_entities,
        parse_mode=media.parse_mode,
        reply_markup=draft_keyboard(draft),
    )


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
