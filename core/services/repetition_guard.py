from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

# Umbral de similitud Jaccard por encima del cual se considera
# repetición. 0.75 = 75% de palabras en común (sobre unión).
JACCARD_THRESHOLD = 0.75

# Número de respuestas previas del bot contra las que comparar.
LOOKBACK = 3


def _tokenize(text: str) -> set[str]:
    """
    Convierte texto a set de tokens normalizados.
    - Minúsculas.
    - Elimina signos de puntuación.
    - Divide por espacios.
    - Filtra tokens de longitud < 2.
    """
    text = text.lower()
    text = re.sub(r"[^\w\sáéíóúüñ]", "", text)
    tokens = {token for token in text.split() if len(token) >= 2}
    return tokens


def jaccard_similarity(a: str, b: str) -> float:
    """
    Calcula similitud de Jaccard entre dos strings.
    Devuelve 0.0 si alguno está vacío.
    """
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def is_repetition(
    candidate: str,
    previous_bot_messages: list[str],
    threshold: float = JACCARD_THRESHOLD,
    lookback: int = LOOKBACK,
) -> bool:
    """
    Devuelve True si candidate es demasiado similar a alguno
    de los últimos `lookback` mensajes del bot.

    previous_bot_messages: lista de textos de respuestas
    anteriores del bot, ordenados del más antiguo al más reciente.
    """
    if not candidate or not previous_bot_messages:
        return False

    recent = previous_bot_messages[-lookback:]
    for prev in recent:
        sim = jaccard_similarity(candidate, prev)
        if sim >= threshold:
            logger.warning(
                "repetition_detected",
                jaccard=round(sim, 3),
                threshold=threshold,
                candidate_preview=candidate[:80],
                prev_preview=prev[:80],
            )
            return True
    return False
