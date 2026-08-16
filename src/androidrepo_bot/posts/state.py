from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from aiogram.fsm.state import State, StatesGroup

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

    from androidrepo_bot.posts.drafts import PreparedDraft
    from androidrepo_bot.posts.models import PostDraft, RegisteredRepository
    from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef

_SESSION_KEY = "draft_session"
_DOWNLOAD_CONFIRMATION_KEY = "download_confirmation"


class PostDraftState(StatesGroup):
    active = State()
    confirming_publication = State()
    awaiting_download_confirmation = State()


class DraftPhase(StrEnum):
    ACTIVE = "active"
    CONFIRMING_PUBLICATION = "confirming_publication"


@dataclass(frozen=True, slots=True)
class DraftSession:
    message_id: int
    repository: RepositoryDetails
    draft: PostDraft
    registered_repository: RegisteredRepository
    phase: DraftPhase = DraftPhase.ACTIVE
    notice_message_id: int | None = None

    def confirming_publication(self) -> DraftSession:
        return replace(self, phase=DraftPhase.CONFIRMING_PUBLICATION)

    def active(self) -> DraftSession:
        return replace(self, phase=DraftPhase.ACTIVE)

    def revised(self, draft: PostDraft, *, message_id: int) -> DraftSession:
        return replace(self, draft=draft, message_id=message_id, phase=DraftPhase.ACTIVE)

    def with_notice(self, notice_message_id: int) -> DraftSession:
        return replace(self, notice_message_id=notice_message_id)


@dataclass(frozen=True, slots=True)
class DownloadConfirmation:
    repository: RepositoryRef


class DraftState:
    def __init__(self, context: FSMContext) -> None:
        self._context = context

    async def load(self) -> DraftSession | None:
        phase = _phase_for_state(await self._context.get_state())
        session = (await self._context.get_data()).get(_SESSION_KEY)
        if phase is None or not isinstance(session, DraftSession) or session.phase is not phase:
            return None
        return session

    async def begin(self, prepared: PreparedDraft, *, message_id: int) -> DraftSession:
        session = DraftSession(
            message_id=message_id,
            repository=prepared.repository,
            draft=prepared.draft,
            registered_repository=prepared.registered_repository,
        )
        await self.save(session)
        return session

    async def save(self, session: DraftSession) -> None:
        await self._context.set_data({_SESSION_KEY: session})
        await self._context.set_state(_state_for_phase(session.phase))

    async def wait_for_download(self, repository: RepositoryRef) -> None:
        await self._context.set_data({_DOWNLOAD_CONFIRMATION_KEY: DownloadConfirmation(repository)})
        await self._context.set_state(PostDraftState.awaiting_download_confirmation)

    async def pending_download(self) -> DownloadConfirmation | None:
        if await self._context.get_state() != PostDraftState.awaiting_download_confirmation.state:
            return None
        pending = (await self._context.get_data()).get(_DOWNLOAD_CONFIRMATION_KEY)
        return pending if isinstance(pending, DownloadConfirmation) else None

    async def clear(self) -> DraftSession | None:
        session = await self.load()
        await self._context.clear()
        return session


def _state_for_phase(phase: DraftPhase) -> State:
    match phase:
        case DraftPhase.ACTIVE:
            return PostDraftState.active
        case DraftPhase.CONFIRMING_PUBLICATION:
            return PostDraftState.confirming_publication


def _phase_for_state(state: str | None) -> DraftPhase | None:
    if state == PostDraftState.active.state:
        return DraftPhase.ACTIVE
    if state == PostDraftState.confirming_publication.state:
        return DraftPhase.CONFIRMING_PUBLICATION
    return None
