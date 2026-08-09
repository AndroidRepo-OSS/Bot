from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from androidrepo_bot.repositories.models import RepositoryDetails


@dataclass(frozen=True, slots=True)
class GenerationContext:
    repository: RepositoryDetails
    allow_missing_download: bool = False
