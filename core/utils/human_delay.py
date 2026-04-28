from __future__ import annotations

import asyncio
import random

import structlog

logger = structlog.get_logger(__name__)

# Velocidad base de escritura humana (caracteres por segundo)
CHARS_PER_SECOND = 60.0

# Limites del delay base antes de varianza log-normal
MIN_BASE_SECONDS = 1.0
MAX_BASE_SECONDS = 6.0

# Parametros de la distribucion log-normal
LOGNORM_MU = 0.0
LOGNORM_SIGMA = 0.4

# Hard clamp final del delay
MIN_DELAY = 1.0
MAX_DELAY = 8.0


def compute_delay(text: str) -> float:
    """
    Calcula el delay log-normal para un mensaje de texto dado.
    Reproducible con seed para tests. Puro (sin IO).
    """
    base = len(text) / CHARS_PER_SECOND
    base_clamped = max(MIN_BASE_SECONDS, min(MAX_BASE_SECONDS, base))
    jitter = random.lognormvariate(LOGNORM_MU, LOGNORM_SIGMA)
    delay = base_clamped * jitter
    return max(MIN_DELAY, min(MAX_DELAY, delay))


async def human_delay(text: str, correlation_id: str | None = None) -> float:
    """
    Espera un tiempo log-normal proporcional a la longitud del texto.
    Devuelve el delay real aplicado (en segundos).
    Loggea el delay para trazabilidad.
    """
    delay = compute_delay(text)
    logger.debug(
        "human_delay_applied",
        delay_seconds=round(delay, 3),
        text_length=len(text),
        correlation_id=correlation_id,
    )
    await asyncio.sleep(delay)
    return delay
