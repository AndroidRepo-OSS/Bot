import structlog
import uvloop

from androidrepo_bot.app import run_bot
from androidrepo_bot.config import Settings
from androidrepo_bot.log_config import configure_logging

logger = structlog.get_logger(__name__)


def main() -> None:
    settings = Settings.model_validate({})
    configure_logging(settings.log_level)
    try:
        uvloop.run(run_bot(settings))
    except KeyboardInterrupt:
        logger.info("Bot stopped by the operator")
