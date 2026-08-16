from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, TypeAdapter

_ASCII_CONTROL_LIMIT = 32
_ASCII_DELETE = 127


def require_repository_path(value: str) -> str:
    candidate = value.strip().strip("/")
    parts = candidate.split("/")
    if (
        not candidate
        or "\\" in candidate
        or any(
            character.isspace() or ord(character) < _ASCII_CONTROL_LIMIT or ord(character) == _ASCII_DELETE
            for character in candidate
        )
        or any(part in {"", ".", ".."} for part in parts)
    ):
        msg = "Repository file path is invalid"
        raise ValueError(msg)
    return candidate


type ProviderFilePath = Annotated[str, AfterValidator(require_repository_path)]


class ProviderPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=False)


_LANGUAGE_USAGE_ADAPTER = TypeAdapter(dict[str, int | float], config=ConfigDict(strict=True, allow_inf_nan=False))


def parse_language_ranking(content: bytes) -> tuple[str, ...]:
    languages = _LANGUAGE_USAGE_ADAPTER.validate_json(content)
    return tuple(name for name, _ in sorted(languages.items(), key=lambda item: (-item[1], item[0].casefold())))
