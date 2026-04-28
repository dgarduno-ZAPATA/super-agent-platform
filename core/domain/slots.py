from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LeadSlots:
    """
    Slots estructurados del lead extraídos de la conversación.

    REGLA NULL ESTRICTA: Un slot es None si y solo si el cliente
    NO lo mencionó explícitamente en la conversación. Ningún método
    de extracción puede inferir, completar o estimar un slot a partir
    de contexto, historial o suposiciones. Si hay duda, el valor es None.
    Devolver None es correcto. Devolver un valor incorrecto contamina el CRM.
    """

    name: str | None = None
    city: str | None = None
    vehicle_interest: str | None = None
    budget: float | None = None
    phone: str | None = None
    contact_preference: str | None = None


@dataclass
class SlotExtractionResult:
    slots: LeadSlots
    extraction_method: str  # "regex" | "none"
    raw_matches: dict[str, str] = field(default_factory=dict)
    # raw_matches: qué texto del cliente originó cada slot no-None
    # ejemplo: {"name": "me llamo Diego", "city": "soy de Guadalajara"}
