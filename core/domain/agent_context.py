from __future__ import annotations

from dataclasses import dataclass

from core.domain.action import AgentAction
from core.domain.intent import Intent
from core.domain.slots import LeadSlots


@dataclass
class AgentContext:
    """
    Único objeto que debe llegar al LLM para redactar una respuesta.
    El LLM no recibe el InboundEvent completo ni el estado FSM crudo.
    Solo recibe lo que el código decidió que necesita saber.
    """

    intent: Intent
    action: AgentAction
    slots: LeadSlots
    fsm_state: str
    inventory_results: list[dict[str, object]] | None
    conversation_history: list[dict[str, object]]  # últimas N interacciones
    brand_name: str
    lead_id: str | None = None
    correlation_id: str | None = None
