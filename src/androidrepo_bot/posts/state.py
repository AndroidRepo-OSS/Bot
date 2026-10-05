from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from aiogram.fsm.state import State, StatesGroup

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

    from androidrepo_bot.db.repositories import RegisteredRepository
    from androidrepo_bot.generation.models import PostDraft
    from androidrepo_bot.posts.drafts import PreparedDraft
    from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef

_SESSION_KEY = "draft_session"
_DOWNLOAD_CONFIRMATION_KEY = "download_confirmation"


class PostDraftState(StatesGroup):
    active = State()
    confirming_publication = State()
    awaiting_download_confirmation = State()


@dataclass(frozen=True, slots=True)
class DraftSession:
    owner_user_id: int
    message_id: int
    repository: RepositoryDetails
    draft: PostDraft
    registered_repository: RegisteredRepository
    notice_message_id: int | None = None

    def revised(self, draft: PostDraft, *, message_id: int) -> DraftSession:
        return replace(self, draft=draft, message_id=message_id)

    def with_notice(self, notice_message_id: int) -> DraftSession:
        return replace(self, notice_message_id=notice_message_id)


@dataclass(frozen=True, slots=True)
class DownloadConfirmation:
    repository: RepositoryRef
    message_id: int
    owner_user_id: int


class DraftState:
    """Typed access to the process-local FSM storage, isolated per staff member."""

    def __init__(self, context: FSMContext) -> None:
        self._context = context

    async def load(self) -> DraftSession | None:
        status = await self._context.get_state()
        if status not in {PostDraftState.active.state, PostDraftState.confirming_publication.state}:
            return None
        session = await self._context.get_value(_SESSION_KEY)
        return session if isinstance(session, DraftSession) else None

    async def begin(self, prepared: PreparedDraft, *, message_id: int, owner_user_id: int) -> DraftSession:
        session = DraftSession(
            owner_user_id=owner_user_id,
            message_id=message_id,
            repository=prepared.repository,
            draft=prepared.draft,
            registered_repository=prepared.registered_repository,
        )
        await self.save(session)
        return session

    async def save(self, session: DraftSession, *, status: State = PostDraftState.active) -> None:
        await self._context.set_data({_SESSION_KEY: session})
        await self._context.set_state(status)

    async def wait_for_download(self, repository: RepositoryRef, *, message_id: int, owner_user_id: int) -> None:
        await self._context.set_data({
            _DOWNLOAD_CONFIRMATION_KEY: DownloadConfirmation(repository, message_id, owner_user_id)
        })
        await self._context.set_state(PostDraftState.awaiting_download_confirmation)

    async def pending_download(self) -> DownloadConfirmation | None:
        if await self._context.get_state() != PostDraftState.awaiting_download_confirmation.state:
            return None
        pending = await self._context.get_value(_DOWNLOAD_CONFIRMATION_KEY)
        return pending if isinstance(pending, DownloadConfirmation) else None

    async def clear(self) -> None:
        await self._context.clear()
