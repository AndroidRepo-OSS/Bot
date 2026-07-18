import logging
import re
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, TypeIs

import structlog
from structlog.tracebacks import ExceptionDictTransformer

if TYPE_CHECKING:
    from androidrepo_bot.config import LogLevel

_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*")
_QUERY_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|password|secret|token)=([^&\s]+)")
_TELEGRAM_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


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
            _redact_secrets,
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
    root_logger = logging.getLogger()
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
            _redact_secrets,
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
    if _is_object_mapping(value):
        return {key: _redact_value(item) for key, item in value.items()}
    if _is_object_list(value):
        return [_redact_value(item) for item in value]
    if _is_object_tuple(value):
        return tuple(_redact_value(item) for item in value)
    return value


def _is_object_mapping(value: object) -> TypeIs[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_object_tuple(value: object) -> TypeIs[tuple[object, ...]]:
    return isinstance(value, tuple)
