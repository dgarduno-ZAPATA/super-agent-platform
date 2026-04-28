from __future__ import annotations

# Mapa de estado FSM → tools permitidas para el LLM.
# Lista vacía = LLM responde sin tools (solo redacta).
# Estado no configurado = sin tools (safe default).
FSM_TOOL_POLICY: dict[str, list[str]] = {
    "idle": [],
    "greeting": [],
    "discovery": ["query_inventory"],
    "qualification": [],
    "catalog_navigation": ["query_inventory", "send_inventory_photos"],
    "document_delivery": [],
    "objection_handling": ["query_inventory"],
    "appointment_flow": [],
    "handoff_pending": [],
    "handoff_active": [],
    "cooldown": [],
    "closed": [],
}


def get_allowed_tools(fsm_state: str) -> list[str]:
    """
    Devuelve las tools que el LLM puede llamar en el estado dado.
    Si el estado no está en el mapa, devuelve lista vacía (safe default).
    """
    return FSM_TOOL_POLICY.get(fsm_state, [])
