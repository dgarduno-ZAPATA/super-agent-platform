from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_correlation_context: ContextVar[dict[str, str]] = ContextVar(
    "correlation_context",
    default={},
)


def bind_context(**kwargs: object) -> None:
    current = dict(_correlation_context.get())

    for key, value in kwargs.items():
        if value is None:
            continue
        current[key] = str(value)

    _correlation_context.set(current)


def clear_context() -> None:
    _correlation_context.set({})


def get_context() -> dict[str, str]:
    return dict(_correlation_context.get())
