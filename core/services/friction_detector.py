from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

FRICTION_KEYWORDS: list[str] = [
    "no entiendo",
    "no me entiendes",
    "no entendiste",
    "no es lo que busco",
    "eso no",
    "no es eso",
    "otra vez",
    "ya te dije",
    "te lo repetí",
    "sigues sin",
    "insisto",
    "qué no entiendes",
    "no me ayudas",
    "no sirves",
    "para qué",
]

# Mínimo de mensajes de fricción en los últimos N para escalar.
FRICTION_MSG_THRESHOLD = 2
FRICTION_LOOKBACK = 3

# Mínimo de turnos en el mismo estado FSM para considerar
# que no hay progreso.
STALE_STATE_THRESHOLD = 3


def _has_friction_keyword(text: str) -> bool:
    text_lower = re.sub(r"\s+", " ", text.lower()).strip()
    return any(keyword in text_lower for keyword in FRICTION_KEYWORDS)


def detect_friction(
    current_client_message: str,
    recent_client_messages: list[str],
    current_state: str,
    recent_states: list[str],
) -> bool:
    """
    Devuelve True si se detecta fricción conversacional.

    Parámetros:
    - current_client_message: texto del mensaje actual del cliente.
    - recent_client_messages: últimos N mensajes del cliente
      (sin incluir el actual), del más antiguo al más reciente.
    - current_state: estado FSM actual.
    - recent_states: estados FSM de los últimos N turnos
      (sin incluir el actual), del más antiguo al más reciente.
    """
    if len(recent_states) >= STALE_STATE_THRESHOLD:
        last_n = recent_states[-STALE_STATE_THRESHOLD:]
        if all(state == current_state for state in last_n):
            logger.info(
                "friction_stale_state",
                current_state=current_state,
                stale_turns=STALE_STATE_THRESHOLD,
            )
            return True

    window = recent_client_messages[-(FRICTION_LOOKBACK - 1) :] + [current_client_message]
    friction_count = sum(1 for message in window if _has_friction_keyword(message))
    if friction_count >= FRICTION_MSG_THRESHOLD:
        logger.warning(
            "friction_keywords_detected",
            count=friction_count,
            threshold=FRICTION_MSG_THRESHOLD,
        )
        return True

    return False
