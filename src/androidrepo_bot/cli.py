from typing import TYPE_CHECKING, cast

import structlog
import uvloop

from androidrepo_bot.app import run_bot
from androidrepo_bot.config import Settings
from androidrepo_bot.log_config import configure_logging

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


def main() -> None:
    settings = cast("Callable[[], Settings]", Settings)()
    configure_logging(settings.log_level)
    try:
        uvloop.run(run_bot(settings))
    except KeyboardInterrupt:
        logger.info("Bot stopped by the operator")
