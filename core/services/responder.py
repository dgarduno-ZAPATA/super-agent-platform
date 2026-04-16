from __future__ import annotations

import structlog

from core.brand.schema import Brand
from core.domain.messaging import InboundEvent, MessageKind
from core.domain.session import Session
from core.ports.messaging_provider import MessagingProvider

logger = structlog.get_logger("super_agent_platform.core.services.responder")


class EchoResponder:
    def __init__(self, messaging_provider: MessagingProvider, brand: Brand) -> None:
        self._messaging_provider = messaging_provider
        self._brand = brand

    async def respond(self, event: InboundEvent, session: Session) -> None:
        text = self._build_response_text(event)
        correlation_id = self._extract_correlation_id(event)

        try:
            await self._messaging_provider.send_text(
                to=event.from_phone,
                text=text,
                correlation_id=correlation_id,
            )
            logger.info(
                "echo_response_sent",
                to=event.from_phone,
                lead_id=str(session.lead_id),
                session_id=str(session.id),
                message_kind=event.kind.value,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.exception(
                "echo_response_send_failed",
                to=event.from_phone,
                lead_id=str(session.lead_id),
                session_id=str(session.id),
                message_kind=event.kind.value,
                correlation_id=correlation_id,
            )

    def _build_response_text(self, event: InboundEvent) -> str:
        prefix = self._brand.brand.display_name

        if event.kind is MessageKind.TEXT:
            return f"{prefix}: {event.text or ''}".strip()

        if event.kind is MessageKind.AUDIO:
            transcribed_text = event.metadata.get("transcription_text")
            if isinstance(transcribed_text, str) and transcribed_text:
                return f"{prefix} (transcripción): {transcribed_text}"
            fallback = event.text or "Audio transcription not yet implemented"
            return f"{prefix} (transcripción): {fallback}"

        if event.kind is MessageKind.UNSUPPORTED:
            return (
                f"{prefix}: Recibí tu mensaje pero no puedo procesar ese tipo de contenido todavía."
            )

        if event.kind in {MessageKind.IMAGE, MessageKind.DOCUMENT, MessageKind.VIDEO}:
            return f"{prefix}: Recibí tu archivo, gracias."

        return f"{prefix}: Recibí tu mensaje."

    @staticmethod
    def _extract_correlation_id(event: InboundEvent) -> str:
        correlation_id = event.metadata.get("correlation_id")
        if isinstance(correlation_id, str) and correlation_id:
            return correlation_id
        return event.message_id
