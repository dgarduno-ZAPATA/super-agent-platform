from __future__ import annotations

import unicodedata
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


def _normalize_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.casefold()


def user_requested_handoff_guard(context: dict[str, object]) -> bool:
    """
    True si el texto del cliente contiene solicitud explícita de hablar con un humano.
    """
    text = _normalize_text(context.get("inbound_text", ""))
    keywords = [
        "asesor",
        "humano",
        "persona real",
        "agente",
        "vendedor",
        "ejecutivo",
        "quiero hablar",
        "hablar con alguien",
        "me comunicas",
        "comunica me",
        "comunicame",
        "transfiere",
        "transferir",
        "con alguien",
    ]
    return any(keyword in text for keyword in keywords)


def has_vehicle_interest_guard(context: dict[str, object]) -> bool:
    """True si el lead tiene vehicle_interest no vacío."""
    val = context.get("vehicle_interest") or context.get("vehiculo_interes")
    return bool(val and str(val).strip())


def has_budget_guard(context: dict[str, object]) -> bool:
    """True si el lead tiene budget mayor a cero."""
    val = context.get("budget")
    try:
        return float(str(val)) > 0
    except (TypeError, ValueError):
        return False


def build_default_guard_registry() -> GuardRegistry:
    return {
        "always": always_guard,
        "has_phone_number": has_phone_number_guard,
        "is_not_silenced": is_not_silenced_guard,
        "opt_out_detected": opt_out_detected_guard,
        "has_name": has_name_guard,
        "user_requested_document": user_requested_document_guard,
        "user_requested_handoff": user_requested_handoff_guard,
        "has_vehicle_interest": has_vehicle_interest_guard,
        "has_budget": has_budget_guard,
    }
