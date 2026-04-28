from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ActionType(str, Enum):
    RESPOND = "respond"
    # LLM redacta respuesta en el estado actual sin tools adicionales

    RESPOND_WITH_INVENTORY = "respond_with_inventory"
    # LLM puede llamar query_inventory antes de responder

    RESPOND_WITH_PHOTOS = "respond_with_photos"
    # LLM puede llamar send_inventory_photos antes de responder

    REQUEST_SLOT = "request_slot"
    # El código pide un dato específico al cliente (name gate, etc.)

    TRIGGER_HANDOFF = "trigger_handoff"
    # Escalar a humano inmediatamente

    RESPOND_NO_DATA = "respond_no_data"
    # Responder sin datos de inventario (Sheet no disponible)

    RESPOND_POST_HANDOFF = "respond_post_handoff"
    # Bot está en silencio post-handoff; respuesta mínima si cliente reabre


@dataclass
class AgentAction:
    type: ActionType
    allowed_tools: list[str] = field(default_factory=list)
    # Herramientas que el LLM tiene PERMITIDO llamar en esta acción.
    # Si la lista está vacía, el LLM NO puede llamar ninguna tool.
    # El ejecutor de tool-calling DEBE respetar esta lista.
    # Valores posibles: "query_inventory", "send_inventory_photos",
    #                   "query_knowledge_base"
    # "send_document" está excluido globalmente (Sprint A).
    required_slots: list[str] = field(default_factory=list)
    # Slots que deben estar presentes antes de ejecutar esta acción.
    context: dict[str, object] = field(default_factory=dict)
    # Datos adicionales que el LLM necesita para redactar.
