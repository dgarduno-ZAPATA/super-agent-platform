from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from core.brand.loader import load_brand
from core.domain.conversation_event import ConversationEvent
from core.domain.llm import LLMResponse, ToolSchema
from core.domain.messaging import ChatMessage, InboundEvent, MessageDeliveryReceipt, MessageKind
from core.domain.session import Session
from core.services.conversation_agent import ConversationAgent


class FakeLLMProvider:
    def __init__(self, content: str = "Respuesta generada") -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "system": system,
                "tools": tools,
                "temperature": temperature,
            }
        )
        return LLMResponse(content=self.content, finish_reason="stop", metadata={"model": "fake"})

    async def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise NotImplementedError

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes
        del mime_type
        raise NotImplementedError


class FakeMessagingProvider:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        self.sent_messages.append({"to": to, "text": text, "correlation_id": correlation_id})
        return MessageDeliveryReceipt(
            message_id="outbound-001",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to
        del image_url
        del caption
        del correlation_id
        raise NotImplementedError

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to
        del document_url
        del filename
        del correlation_id
        raise NotImplementedError

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to
        del audio_url
        del correlation_id
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        del message_id
        raise NotImplementedError

    def parse_inbound_event(self, raw_payload: dict[str, object]) -> InboundEvent:
        del raw_payload
        raise NotImplementedError


class FakeConversationEventRepository:
    def __init__(self, seed_events: list[ConversationEvent] | None = None) -> None:
        self.events = list(seed_events or [])
        self.append_calls = 0

    async def append(self, event: ConversationEvent) -> bool:
        self.append_calls += 1
        self.events.append(event)
        return True

    async def list_by_conversation(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[ConversationEvent]:
        filtered = [item for item in self.events if item.conversation_id == conversation_id]
        return filtered[:limit]


def _conversation_id(phone: str = "5214421234567") -> UUID:
    return uuid5(NAMESPACE_URL, f"whatsapp:{phone}")


def _event(text: str = "Hola", phone: str = "5214421234567") -> InboundEvent:
    now = datetime.now(UTC)
    return InboundEvent(
        message_id="wamid-123",
        from_phone=phone,
        kind=MessageKind.TEXT,
        text=text,
        media_url=None,
        raw_metadata={},
        received_at=now,
        sender_id=f"{phone}@s.whatsapp.net",
        channel="whatsapp",
        event_type="inbound_message",
        occurred_at=now,
        metadata={},
    )


def _session(state: str = "discovery") -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        lead_id=uuid4(),
        current_state=state,
        context={},
        created_at=now,
        updated_at=now,
        last_event_at=now,
    )


@pytest.mark.asyncio
async def test_prompt_includes_current_fsm_state() -> None:
    brand = load_brand(Path("brand"))
    llm = FakeLLMProvider()
    messaging = FakeMessagingProvider()
    event_repo = FakeConversationEventRepository(
        seed_events=[
            ConversationEvent(
                id=uuid4(),
                conversation_id=_conversation_id(),
                lead_id=None,
                event_type="inbound_message",
                payload={"text": "Hola"},
                created_at=datetime.now(UTC),
                message_id="inbound-1",
            )
        ]
    )
    agent = ConversationAgent(
        llm_provider=llm,
        messaging_provider=messaging,
        brand=brand,
        conversation_event_repository=event_repo,
    )

    await agent.respond(_event("Necesito cotizacion"), _session("qualification"))

    system_prompt = str(llm.calls[0]["system"])
    assert "ESTADO ACTUAL: qualification" in system_prompt


@pytest.mark.asyncio
async def test_calls_llm_then_messaging_provider() -> None:
    brand = load_brand(Path("brand"))
    llm = FakeLLMProvider(content="Texto desde LLM")
    messaging = FakeMessagingProvider()
    event_repo = FakeConversationEventRepository()
    agent = ConversationAgent(
        llm_provider=llm,
        messaging_provider=messaging,
        brand=brand,
        conversation_event_repository=event_repo,
    )

    await agent.respond(_event("Hola"), _session("greeting"))

    assert len(llm.calls) == 1
    assert len(messaging.sent_messages) == 1
    assert messaging.sent_messages[0]["text"] == "Texto desde LLM"


@pytest.mark.asyncio
async def test_persists_outbound_message_in_event_repository() -> None:
    brand = load_brand(Path("brand"))
    llm = FakeLLMProvider(content="Mensaje persistido")
    messaging = FakeMessagingProvider()
    event_repo = FakeConversationEventRepository()
    agent = ConversationAgent(
        llm_provider=llm,
        messaging_provider=messaging,
        brand=brand,
        conversation_event_repository=event_repo,
    )
    session = _session("discovery")

    await agent.respond(_event("Dame opciones"), session)

    outbound = [event for event in event_repo.events if event.event_type == "outbound_message"]
    assert len(outbound) == 1
    assert outbound[0].payload["text"] == "Mensaje persistido"
