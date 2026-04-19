"""Structured logging using structlog (outputs JSON in Lambda, pretty-print locally)."""

import logging
import os

import structlog

_level = logging.DEBUG if os.getenv("ENVIRONMENT", "development") == "development" else logging.INFO

logging.basicConfig(level=_level, format="%(message)s")

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
        if os.getenv("ENVIRONMENT") == "production"
        else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger("ceep")
