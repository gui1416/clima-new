from __future__ import annotations

import logging

import structlog

from clima.config import config

_configurado = False


def configurar() -> None:
    global _configurado
    if _configurado:
        return
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if config().log_json
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    _configurado = True


def log(nome: str) -> structlog.stdlib.BoundLogger:
    configurar()
    return structlog.get_logger(nome)
