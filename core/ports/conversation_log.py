from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ConversationLogPort(Protocol):
    async def log_turn(
        self,
        lead_id: str | None,
        phone_masked: str,
        last_state: str,
        last_intent: str,
        summary: str,
        updated_at: str,
        correlation_id: str | None = None,
    ) -> None:
        """
        Registra un turno de conversación en el log externo.
        Debe ser idempotente: si el lead ya tiene fila, actualizar; si no, crear.
        No debe lanzar excepción si el log falla — loggear el error con structlog y retornar.
        """
        ...
