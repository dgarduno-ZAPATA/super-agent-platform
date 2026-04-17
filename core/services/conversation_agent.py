from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import structlog

from core.brand.schema import Brand
from core.domain.conversation_event import ConversationEvent
from core.domain.messaging import ChatMessage, InboundEvent
from core.domain.session import Session
from core.ports.llm_provider import LLMProvider
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import ConversationEventRepository

logger = structlog.get_logger("super_agent_platform.core.services.conversation_agent")


class ConversationAgent:
    def __init__(
        self,
        llm_provider: LLMProvider,
        messaging_provider: MessagingProvider,
        brand: Brand,
        conversation_event_repository: ConversationEventRepository,
    ) -> None:
        self._llm_provider = llm_provider
        self._messaging_provider = messaging_provider
        self._brand = brand
        self._conversation_event_repository = conversation_event_repository

    async def respond(self, event: InboundEvent, session: Session) -> None:
        correlation_id = self._extract_correlation_id(event)
        conversation_id = self._build_conversation_id(event.from_phone)

        try:
            history = await self._conversation_event_repository.list_by_conversation(
                conversation_id=conversation_id,
                limit=15,
            )
            messages = self._format_history_as_messages(history)
            if not messages:
                messages = [self._build_user_message(event)]

            system_prompt = self._build_system_prompt(session.current_state)
            llm_response = await self._llm_provider.complete(
                messages=messages[-15:],
                system=system_prompt,
                tools=None,
                temperature=0.2,
            )

            delivery = await self._messaging_provider.send_text(
                to=event.from_phone,
                text=llm_response.content,
                correlation_id=correlation_id,
            )
            await self._persist_outbound_event(
                conversation_id=conversation_id,
                lead_id=session.lead_id,
                text=llm_response.content,
                correlation_id=correlation_id,
                provider_message_id=delivery.message_id,
                state=session.current_state,
                llm_metadata=llm_response.metadata,
            )
            logger.info(
                "conversation_agent_response_sent",
                conversation_id=str(conversation_id),
                lead_id=str(session.lead_id),
                state=session.current_state,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.exception(
                "conversation_agent_response_failed",
                conversation_id=str(conversation_id),
                lead_id=str(session.lead_id),
                state=session.current_state,
                correlation_id=correlation_id,
            )

    def _build_system_prompt(self, current_state: str) -> str:
        return (
            f"{self._brand.prompt}\n\n"
            f"ESTADO ACTUAL: {current_state}. "
            "Sigue estrictamente el objetivo de este estado segun tus instrucciones."
        )

    def _format_history_as_messages(self, history: list[ConversationEvent]) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        for item in history:
            role = self._resolve_role(item.event_type)
            if role is None:
                continue
            text = item.payload.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            messages.append(ChatMessage(role=role, content=text.strip()))
        return messages

    @staticmethod
    def _resolve_role(event_type: str) -> str | None:
        if event_type == "inbound_message":
            return "user"
        if event_type == "outbound_message":
            return "assistant"
        return None

    async def _persist_outbound_event(
        self,
        conversation_id: UUID,
        lead_id: UUID,
        text: str,
        correlation_id: str,
        provider_message_id: str,
        state: str,
        llm_metadata: dict[str, object],
    ) -> None:
        outbound_event = ConversationEvent(
            id=uuid4(),
            conversation_id=conversation_id,
            lead_id=lead_id,
            event_type="outbound_message",
            payload={
                "text": text,
                "correlation_id": correlation_id,
                "state": state,
                "llm_metadata": llm_metadata,
                "message_kind": "text",
            },
            created_at=datetime.now(UTC),
            message_id=provider_message_id,
        )
        await self._conversation_event_repository.append(outbound_event)

    @staticmethod
    def _extract_correlation_id(event: InboundEvent) -> str:
        correlation_id = event.metadata.get("correlation_id")
        if isinstance(correlation_id, str) and correlation_id:
            return correlation_id
        return event.message_id

    @staticmethod
    def _build_conversation_id(phone: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"whatsapp:{phone}")

    @staticmethod
    def _build_user_message(event: InboundEvent) -> ChatMessage:
        return ChatMessage(role="user", content=(event.text or "").strip())
