from __future__ import annotations

from collections.abc import Callable

GuardFunction = Callable[[dict[str, object]], bool]
GuardRegistry = dict[str, GuardFunction]


def always_guard(context: dict[str, object]) -> bool:
    del context
    return True


def has_phone_number_guard(context: dict[str, object]) -> bool:
    return context.get("phone") is not None


def is_not_silenced_guard(context: dict[str, object]) -> bool:
    return not bool(context.get("is_silenced", False))


def opt_out_detected_guard(context: dict[str, object]) -> bool:
    return bool(context.get("opt_out_detected", False))


def has_name_guard(context: dict[str, object]) -> bool:
    return context.get("name") is not None


def user_requested_document_guard(context: dict[str, object]) -> bool:
    text = str(context.get("inbound_text") or "").lower()
    keywords = [
        "ficha",
        "pdf",
        "documento",
        "técnica",
        "tecnica",
        "catálogo",
        "catalogo",
        "especificaciones",
        "specs",
        "mándame",
        "mandame",
        "envíame",
        "enviame",
        "enviar",
        "corrida",
        "información de la unidad",
        "informacion de la unidad",
    ]
    return any(kw in text for kw in keywords)


def build_default_guard_registry() -> GuardRegistry:
    return {
        "always": always_guard,
        "has_phone_number": has_phone_number_guard,
        "is_not_silenced": is_not_silenced_guard,
        "opt_out_detected": opt_out_detected_guard,
        "has_name": has_name_guard,
        "user_requested_document": user_requested_document_guard,
    }
