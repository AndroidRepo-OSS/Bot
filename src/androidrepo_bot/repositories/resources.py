from asyncio import TaskGroup
from typing import TYPE_CHECKING, Any, Never, TypeIs

from androidrepo_bot.errors import RepositoryAccessError
from androidrepo_bot.repositories.payloads import parse_language_ranking

if TYPE_CHECKING:
    from collections.abc import Coroutine, Iterator, Mapping

    from androidrepo_bot.repositories.http import ProviderTransport


async def fetch_languages(client: ProviderTransport, root: str, headers: Mapping[str, str]) -> tuple[str, ...]:
    response = await client.get_optional(f"{root}/languages", headers=headers)
    if response is None:
        return ()
    return await client.parse(response, parse_language_ranking)


async def fetch_repository_resources[ReadmeT, ReleaseT](
    readme: Coroutine[Any, Any, ReadmeT],
    languages: Coroutine[Any, Any, tuple[str, ...]],
    release: Coroutine[Any, Any, ReleaseT],
) -> tuple[ReadmeT, tuple[str, ...], ReleaseT]:
    try:
        async with TaskGroup() as tasks:
            readme_task = tasks.create_task(readme)
            languages_task = tasks.create_task(languages)
            release_task = tasks.create_task(release)
    except ExceptionGroup as error:
        _raise_resource_error(error)
    return readme_task.result(), languages_task.result(), release_task.result()


def _raise_resource_error(error: ExceptionGroup[Exception], /) -> Never:
    for exception in _iter_group_exceptions(error):
        if isinstance(exception, (RepositoryAccessError, ValueError)):
            raise exception from error
    raise error


def _iter_group_exceptions(error: BaseExceptionGroup[BaseException]) -> Iterator[BaseException]:
    for exception in error.exceptions:
        if _is_base_exception_group(exception):
            yield from _iter_group_exceptions(exception)
        else:
            yield exception


def _is_base_exception_group(value: BaseException) -> TypeIs[BaseExceptionGroup[BaseException]]:
    return isinstance(value, BaseExceptionGroup)
