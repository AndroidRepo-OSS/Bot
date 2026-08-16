from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import Insert, insert

from androidrepo_bot.db.models import RepositoryAlias, RepositoryApp
from androidrepo_bot.posts.models import RegisteredRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from sqlalchemy.sql.dml import ReturningInsert

    from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef


async def register_repository(
    sessions: async_sessionmaker[AsyncSession], repository: RepositoryDetails, requested: RepositoryRef
) -> RegisteredRepository:
    if requested.provider is not repository.ref.provider:
        msg = "requested and canonical repositories must use the same provider"
        raise ValueError(msg)

    seen_at = datetime.now(UTC)
    async with sessions.begin() as session:
        repository_id = (await session.execute(_repository_upsert(repository, seen_at))).scalar_one()
        await session.execute(_alias_upsert(repository_id, requested, seen_at))
        if requested != repository.ref:
            await session.execute(_alias_upsert(repository_id, repository.ref, seen_at))

    return RegisteredRepository(id=repository_id, ref=repository.ref)


def _repository_upsert(repository: RepositoryDetails, seen_at: datetime) -> ReturningInsert[tuple[int]]:
    statement = insert(RepositoryApp).values(
        provider=repository.ref.provider.value,
        provider_repository_id=repository.provider_repository_id,
        current_namespace=repository.ref.namespace,
        current_name=repository.ref.name,
        current_url=repository.ref.url,
        display_name=repository.display_name,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    return statement.on_conflict_do_update(
        constraint="uq_repository_apps_provider_id",
        set_={
            "current_namespace": statement.excluded.current_namespace,
            "current_name": statement.excluded.current_name,
            "current_url": statement.excluded.current_url,
            "display_name": statement.excluded.display_name,
            "last_seen_at": statement.excluded.last_seen_at,
        },
    ).returning(RepositoryApp.id)


def _alias_upsert(repository_id: int, repository: RepositoryRef, observed_at: datetime) -> Insert:
    statement = insert(RepositoryAlias).values(
        repository_app_id=repository_id,
        namespace=repository.namespace,
        name=repository.name,
        full_name=repository.full_name,
        url=repository.url,
        observed_at=observed_at,
    )
    return statement.on_conflict_do_update(
        constraint="uq_repository_aliases_repository_value",
        set_={
            "namespace": statement.excluded.namespace,
            "name": statement.excluded.name,
            "observed_at": statement.excluded.observed_at,
        },
    )
