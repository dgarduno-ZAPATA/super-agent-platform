from __future__ import annotations

from contextvars import ContextVar

_correlation_context: ContextVar[dict[str, str] | None] = ContextVar(
    "correlation_context",
    default=None,
)


def bind_context(**kwargs: object) -> None:
    current = dict(_correlation_context.get() or {})

    for key, value in kwargs.items():
        if value is None:
            continue
        current[key] = str(value)

    _correlation_context.set(current)


def clear_context() -> None:
    _correlation_context.set(None)


def get_context() -> dict[str, str]:
    return dict(_correlation_context.get() or {})
