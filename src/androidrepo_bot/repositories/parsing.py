from urllib.parse import urlsplit

from androidrepo_bot.repositories.models import RepositoryProvider, RepositoryRef

_REPOSITORY_ROOT_PARTS = 2


class RepositoryUrlError(ValueError):
    pass


def parse_repository_url(value: str) -> RepositoryRef:
    provider, path = _parse_repository_location(value)
    parts = _repository_path_parts(path, provider=provider)

    try:
        return RepositoryRef(provider=provider, namespace="/".join(parts[:-1]), name=parts[-1])
    except ValueError as error:
        msg = "The URL must point to a repository."
        raise RepositoryUrlError(msg) from error


def _parse_repository_location(value: str) -> tuple[RepositoryProvider, str]:
    candidate = value.strip()
    if not candidate:
        msg = "A repository URL is required."
        raise RepositoryUrlError(msg)

    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as error:
        msg = "The repository URL is malformed."
        raise RepositoryUrlError(msg) from error

    if parsed.scheme.lower() != "https":
        msg = "Only HTTPS repository URLs are supported."
        raise RepositoryUrlError(msg)
    if parsed.username is not None or parsed.password is not None:
        msg = "Credentials are not allowed in repository URLs."
        raise RepositoryUrlError(msg)
    if port is not None:
        msg = "Custom ports are not allowed in repository URLs."
        raise RepositoryUrlError(msg)
    if parsed.query or parsed.fragment:
        msg = "Query strings and fragments are not allowed in repository URLs."
        raise RepositoryUrlError(msg)

    provider = RepositoryProvider.from_host((parsed.hostname or "").lower())
    if provider is None:
        msg = "Only github.com and gitlab.com repositories are supported."
        raise RepositoryUrlError(msg)
    return provider, parsed.path


def _repository_path_parts(path: str, *, provider: RepositoryProvider) -> list[str]:
    if "//" in path or "%" in path:
        msg = "The repository path is malformed."
        raise RepositoryUrlError(msg)

    normalized_path = path.strip("/")
    parts = normalized_path.split("/") if normalized_path else []
    if parts and parts[-1].endswith(".git"):
        parts[-1] = parts[-1][:-4]

    if len(parts) < _REPOSITORY_ROOT_PARTS or any(not part for part in parts):
        msg = "The URL must point to a repository."
        raise RepositoryUrlError(msg)
    if provider is RepositoryProvider.GITHUB and len(parts) != _REPOSITORY_ROOT_PARTS:
        msg = "GitHub repository URLs must use owner/repository."
        raise RepositoryUrlError(msg)
    if provider is RepositoryProvider.GITLAB and "-" in parts:
        msg = "The URL must point to a GitLab repository root."
        raise RepositoryUrlError(msg)
    return parts
