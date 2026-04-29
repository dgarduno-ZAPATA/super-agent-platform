from __future__ import annotations

import structlog

from core.domain.messaging import ChatMessage
from core.ports.llm_provider import LLMProvider

logger = structlog.get_logger(__name__)

SUMMARY_SYSTEM_PROMPT = """
Eres un asistente que genera resumenes concisos de conversaciones
de ventas de camiones para asesores comerciales.
Responde SOLO con el resumen. Maximo 3 oraciones.
Sin saludos, sin explicaciones, solo el resumen.
Idioma: espanol.
"""

SUMMARY_MAX_TOKENS = 150


class ConversationSummaryService:
    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm = llm_provider

    async def generate(
        self,
        conversation_history: list[dict[str, str]],
        trigger_event: str,
        lead_name: str | None = None,
        vehicle_interest: str | None = None,
    ) -> str:
        """
        Genera resumen breve para publicar como nota en Monday.
        """
        if not conversation_history:
            return self._fallback_summary(trigger_event, lead_name, vehicle_interest)

        recent = conversation_history[-6:]
        history_text = "\n".join(
            f"{msg.get('role', 'user').upper()}: {msg.get('content', '')}" for msg in recent
        )
        user_prompt = (
            f"Evento: {trigger_event}\n"
            f"Conversacion reciente:\n{history_text}\n\n"
            "Genera un resumen de 1-3 oraciones para el asesor "
            "que va a atender este lead."
        )

        try:
            response = await self._llm.complete(
                messages=[ChatMessage(role="user", content=user_prompt)],
                system=SUMMARY_SYSTEM_PROMPT,
                tools=None,
                temperature=0.2,
            )
            summary = response.content.strip()
            if not summary:
                return self._fallback_summary(trigger_event, lead_name, vehicle_interest)
            logger.info(
                "conversation_summary_generated",
                trigger_event=trigger_event,
                summary_length=len(summary),
                max_tokens=SUMMARY_MAX_TOKENS,
            )
            return summary
        except Exception as exc:
            logger.warning(
                "conversation_summary_failed",
                trigger_event=trigger_event,
                reason=str(exc),
            )
            return self._fallback_summary(trigger_event, lead_name, vehicle_interest)

    @staticmethod
    def _fallback_summary(
        trigger_event: str,
        lead_name: str | None,
        vehicle_interest: str | None,
    ) -> str:
        parts = [f"Evento: {trigger_event}."]
        if lead_name:
            parts.append(f"Lead: {lead_name}.")
        if vehicle_interest:
            parts.append(f"Interes: {vehicle_interest}.")
        return " ".join(parts)
