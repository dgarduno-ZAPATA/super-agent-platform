from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from core.brand.loader import load_brand
from core.domain.conversation_event import ConversationEvent
from core.domain.llm import LLMResponse, ToolCall, ToolResult, ToolSchema
from core.domain.messaging import ChatMessage, InboundEvent, MessageDeliveryReceipt, MessageKind
from core.domain.session import Session
from core.services.conversation_agent import ConversationAgent
from core.services.skills import SkillExecutionContext


class FakeLLMProvider:
    def __init__(
        self,
        content: str = "Respuesta generada",
        first_response: LLMResponse | None = None,
        second_response: LLMResponse | None = None,
    ) -> None:
        self.content = content
        self.first_response = first_response
        self.second_response = second_response
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        call_index = len(self.calls)
        self.calls.append(
            {
                "messages": messages,
                "system": system,
                "tools": tools,
                "temperature": temperature,
            }
        )
        if call_index == 0 and self.first_response is not None:
            return self.first_response
        if call_index == 1 and self.second_response is not None:
            return self.second_response
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


class FakeSkillRegistry:
    def __init__(self, result: ToolResult | None = None) -> None:
        self.result = result or ToolResult(
            tool_call_id="tool-call-1",
            name="query_inventory",
            content="Resultados de inventario: 1. Freightliner Cascadia",
        )
        self.calls: list[tuple[ToolCall, SkillExecutionContext]] = []

    def get_tool_schemas(self) -> list[ToolSchema]:
        return [
            ToolSchema(
                name="query_inventory",
                description="Consulta inventario",
                input_schema={
                    "type": "object",
                    "properties": {"product_name": {"type": "string"}},
                    "required": ["product_name"],
                },
            )
        ]

    async def execute_tool(self, call: ToolCall, context: SkillExecutionContext) -> ToolResult:
        self.calls.append((call, context))
        return self.result


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
        skill_registry=FakeSkillRegistry(),
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
        skill_registry=FakeSkillRegistry(),
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
        skill_registry=FakeSkillRegistry(),
    )
    session = _session("discovery")

    await agent.respond(_event("Dame opciones"), session)

    outbound = [event for event in event_repo.events if event.event_type == "outbound_message"]
    assert len(outbound) == 1
    assert outbound[0].payload["text"] == "Mensaje persistido"


@pytest.mark.asyncio
async def test_tool_call_flow_executes_skill_and_returns_final_text() -> None:
    brand = load_brand(Path("brand"))
    first_response = LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=(
            ToolCall(
                id="call-1",
                name="query_inventory",
                arguments={"product_name": "Cascadia"},
            ),
        ),
    )
    second_response = LLMResponse(
        content="Te comparto opciones de inventario disponibles.",
        finish_reason="stop",
    )
    llm = FakeLLMProvider(first_response=first_response, second_response=second_response)
    messaging = FakeMessagingProvider()
    event_repo = FakeConversationEventRepository()
    skills = FakeSkillRegistry(
        result=ToolResult(
            tool_call_id="call-1",
            name="query_inventory",
            content="Resultados de inventario: 1. Freightliner Cascadia 2020",
        )
    )
    agent = ConversationAgent(
        llm_provider=llm,
        messaging_provider=messaging,
        brand=brand,
        conversation_event_repository=event_repo,
        skill_registry=skills,
    )

    await agent.respond(_event("Busco un Cascadia"), _session("catalog_navigation"))

    assert len(llm.calls) == 2
    assert len(skills.calls) == 1
    second_call_messages = llm.calls[1]["messages"]
    assert isinstance(second_call_messages, list)
    assert any(
        isinstance(message, ChatMessage) and message.role == "tool"
        for message in second_call_messages
    )
    assert messaging.sent_messages[0]["text"] == "Te comparto opciones de inventario disponibles."


@pytest.mark.asyncio
async def test_respond_uses_supplied_history_and_keeps_current_message_last() -> None:
    brand = load_brand(Path("brand"))
    llm = FakeLLMProvider(content="Te comparto opciones de rabon disponibles.")
    messaging = FakeMessagingProvider()
    event_repo = FakeConversationEventRepository()
    agent = ConversationAgent(
        llm_provider=llm,
        messaging_provider=messaging,
        brand=brand,
        conversation_event_repository=event_repo,
        skill_registry=FakeSkillRegistry(),
    )
    conversation_id = _conversation_id()
    now = datetime.now(UTC)
    history = [
        ConversationEvent(
            id=uuid4(),
            conversation_id=conversation_id,
            lead_id=None,
            event_type="inbound_message",
            payload={"text": "Que camiones tienen?"},
            created_at=now,
            message_id="inbound-history-1",
        ),
        ConversationEvent(
            id=uuid4(),
            conversation_id=conversation_id,
            lead_id=None,
            event_type="outbound_message",
            payload={"text": "Para orientarte mejor, que tipo de camion buscas?"},
            created_at=now,
            message_id="outbound-history-1",
        ),
    ]
    session = _session("discovery")

    await agent.respond(
        _event("Busco un rabon"),
        session,
        conversation_history=history,
    )

    first_call_messages = llm.calls[0]["messages"]
    assert isinstance(first_call_messages, list)
    assert len(first_call_messages) == 3
    assert first_call_messages[0] == ChatMessage(role="user", content="Que camiones tienen?")
    assert first_call_messages[1] == ChatMessage(
        role="assistant",
        content="Para orientarte mejor, que tipo de camion buscas?",
    )
    assert first_call_messages[2] == ChatMessage(role="user", content="Busco un rabon")
    assert messaging.sent_messages[0]["text"] == "Te comparto opciones de rabon disponibles."
