from __future__ import annotations

import asyncio
import time

import structlog

logger = structlog.get_logger(__name__)

# TTL en segundos para cada message_id en cache.
# 2 horas es suficiente; si el webhook llega despues, no nos importa.
_CACHE_TTL_SECONDS = 7200.0

# Maximo de IDs en cache para evitar memory leak en sesiones largas.
_CACHE_MAX_SIZE = 5000


class OutboundMessageCache:
    """
    Cache en memoria de message_id que el bot envio.
    Permite distinguir mensajes propios del bot de mensajes
    enviados por el asesor humano desde el mismo numero.

    Thread-safe para uso con asyncio (un solo loop de eventos).
    """

    def __init__(self) -> None:
        # message_id -> timestamp de insercion
        self._cache: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def add(self, message_id: str) -> None:
        """Registra un message_id como enviado por el bot."""
        async with self._lock:
            if len(self._cache) >= _CACHE_MAX_SIZE:
                # Eliminar el 20% mas antiguo
                cutoff = sorted(self._cache.values())[_CACHE_MAX_SIZE // 5]
                self._cache = {k: v for k, v in self._cache.items() if v > cutoff}
            self._cache[message_id] = time.monotonic()
            logger.debug("outbound_cache_add", message_id=message_id)

    async def contains(self, message_id: str) -> bool:
        """
        Devuelve True si el message_id fue enviado por el bot
        y aun esta dentro del TTL.
        """
        async with self._lock:
            ts = self._cache.get(message_id)
            if ts is None:
                return False
            if time.monotonic() - ts > _CACHE_TTL_SECONDS:
                del self._cache[message_id]
                return False
            return True

    async def size(self) -> int:
        """Para tests y monitoreo."""
        async with self._lock:
            return len(self._cache)


# Instancia singleton de modulo; se comparte en el proceso.
# En Cloud Run (single instance) esto es suficiente.
outbound_cache = OutboundMessageCache()
