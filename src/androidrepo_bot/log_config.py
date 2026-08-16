import logging
import re
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

import structlog
from structlog.tracebacks import ExceptionDictTransformer

if TYPE_CHECKING:
    from androidrepo_bot.config import LogLevel

_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*")
_QUERY_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|password|secret|token)=([^&\s]+)")
_TELEGRAM_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
_SECRET_KEY_RE = re.compile(r"(?i)(?:.*[_-])?(?:api[_-]?key|password|secret|token|authorization)")


def configure_logging(level: LogLevel) -> None:
    level_number = logging.getLevelNamesMapping()[level]
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    callsite_adder = structlog.processors.CallsiteParameterAdder({
        structlog.processors.CallsiteParameter.FILENAME,
        structlog.processors.CallsiteParameter.FUNC_NAME,
        structlog.processors.CallsiteParameter.LINENO,
    })
    foreign_pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
    ]
    render_json = not sys.stdout.isatty()
    exception_renderer = (
        structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False))
        if render_json
        else structlog.processors.format_exc_info
    )
    renderer = structlog.processors.JSONRenderer() if render_json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            *foreign_pre_chain,
            structlog.stdlib.ExtraAdder(),
            structlog.processors.UnicodeDecoder(),
            callsite_adder,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            exception_renderer,
            _redact_secrets,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.root
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level_number)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            timestamper,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            exception_renderer,
            structlog.processors.UnicodeDecoder(),
            callsite_adder,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _redact_secrets(_: object, __: str, event_dict: structlog.types.EventDict) -> structlog.types.EventDict:
    for key, value in event_dict.items():
        event_dict[key] = _redact_value(value)
    return event_dict


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        redacted = _TELEGRAM_BOT_TOKEN_RE.sub("bot<redacted>", value)
        redacted = _BEARER_TOKEN_RE.sub("Bearer <redacted>", redacted)
        return _QUERY_SECRET_RE.sub(r"\1=<redacted>", redacted)
    if isinstance(value, Mapping):
        return {
            key: "<redacted>" if isinstance(key, str) and _SECRET_KEY_RE.fullmatch(key) else _redact_value(item)
            for key, item in cast("Mapping[object, object]", value).items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in cast("tuple[object, ...]", value))
    return value
