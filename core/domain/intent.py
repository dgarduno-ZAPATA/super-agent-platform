from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntentType(str, Enum):
    GREETING = "greeting"
    INVENTORY_QUERY = "inventory_query"
    PRICE_REQUEST = "price_request"
    DOCUMENT_REQUEST = "document_request"
    HANDOFF_REQUEST = "handoff_request"
    OBJECTION = "objection"
    QUALIFICATION = "qualification"
    OPT_OUT = "opt_out"
    UNKNOWN = "unknown"


@dataclass
class Intent:
    type: IntentType
    confidence: float  # 0.0–1.0
    raw_text: str  # texto original del cliente, solo para debug
    detected_by: str  # "regex" | "llm" | "fsm_guard"
