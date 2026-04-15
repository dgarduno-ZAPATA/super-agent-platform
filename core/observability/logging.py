from __future__ import annotations

import logging
import re
import sys
from typing import Any, Literal

import structlog

from core.observability.context import get_context


def mask_pii(value: str, kind: Literal["phone", "email", "name"]) -> str:
    if kind == "phone":
        digits = "".join(character for character in value if character.isdigit())
        if not digits:
            return "***"
        visible = digits[-4:] if len(digits) >= 4 else digits
        prefix = "+52" if digits.startswith("52") or value.strip().startswith("+52") else ""
        return f"{prefix}***{visible}"

    if kind == "email":
        local_part, separator, domain = value.partition("@")
        if not separator or not local_part or not domain:
            return "***"
        visible_local = local_part[:1]
        visible_domain = domain[:1]
        return f"{visible_local}***@{visible_domain}***"

    normalized = " ".join(part for part in value.split() if part)
    if not normalized:
        return "***"

    parts = normalized.split(" ")
    masked_parts: list[str] = []
    for part in parts:
        if len(part) <= 1:
            masked_parts.append("*")
        else:
            masked_parts.append(f"{part[0]}***")
    return " ".join(masked_parts)


def _mask_event_dict(_: Any, __: str, event_dict: structlog.typing.EventDict) -> structlog.typing.EventDict:
    pii_fields: dict[str, Literal["phone", "email", "name"]] = {
        "phone": "phone",
        "email": "email",
        "name": "name",
        "lead_phone": "phone",
        "lead_email": "email",
        "lead_name": "name",
    }

    for field_name, kind in pii_fields.items():
        raw_value = event_dict.get(field_name)
        if isinstance(raw_value, str):
            event_dict[field_name] = mask_pii(raw_value, kind)

    return event_dict


def _inject_correlation_context(
    _: Any, __: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    for key, value in get_context().items():
        event_dict.setdefault(key, value)
    return event_dict


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stdout,
        force=True,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_correlation_context,
        _mask_event_dict,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


REQUEST_ID_HEADER = "X-Request-ID"
