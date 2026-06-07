from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from argus.shared.config import settings


def setup_logging() -> None:
    level = getattr(logging, settings.app_log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
            if sys.stderr.isatty()
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)

    # Quiet noisy third-party loggers
    for name in ("httpx", "httpcore", "urllib3", "chardet"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger = structlog.get_logger(name)
    return logger  # type: ignore[no-any-return]


def bind_context(
    task_id: str | None = None,
    step_id: int | None = None,
    component: str | None = None,
) -> None:
    ctx: dict[str, Any] = {}
    if task_id is not None:
        ctx["task_id"] = task_id
    if step_id is not None:
        ctx["step_id"] = step_id
    if component is not None:
        ctx["component"] = component
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)


def unbind_context() -> None:
    structlog.contextvars.clear_contextvars()
