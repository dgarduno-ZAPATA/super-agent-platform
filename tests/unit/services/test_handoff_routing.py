from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.domain.branch import Branch
from core.domain.classification import MessageClassification
from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.messaging import InboundEvent, MessageDeliveryReceipt, MessageKind
from core.domain.session import Session
from core.fsm.schema import FSMConfig
from core.services.inbound_handler import InboundMessageHandler


class FakeMessagingProvider:
    def __init__(self, inbound_event: InboundEvent) -> None:
        self._inbound_event = inbound_event
        self.sent_messages: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        self.sent_messages.append({"to": to, "text": text, "correlation_id": correlation_id})
        return MessageDeliveryReceipt(
            message_id="out-1",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to, image_url, caption, correlation_id
        raise NotImplementedError

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to, document_url, filename, correlation_id
        raise NotImplementedError

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to, audio_url, correlation_id
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        del message_id
        raise NotImplementedError

    def parse_inbound_event(self, raw_payload: dict[str, object]) -> InboundEvent:
        del raw_payload
        return self._inbound_event


class FakeConversationEventRepository:
    def __init__(self) -> None:
        self.events: list[ConversationEvent] = []

    async def append(self, event: ConversationEvent) -> bool:
        self.events.append(event)
        return True

    async def list_by_conversation(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[ConversationEvent]:
        return [item for item in self.events if item.conversation_id == conversation_id][:limit]


class FakeLeadProfileRepository:
    def __init__(self, lead: LeadProfile | None = None) -> None:
        self._lead = lead

    async def get_by_phone(self, phone: str) -> LeadProfile | None:
        del phone
        return self._lead

    async def upsert_by_phone(self, profile: LeadProfile) -> LeadProfile:
        self._lead = profile
        return profile


class FakeCRMOutboxRepository:
    async def enqueue_operation(
        self, aggregate_id: str, operation: str, payload: dict[str, object]
    ) -> UUID:
        del aggregate_id, operation, payload
        return UUID("00000000-0000-0000-0000-000000000001")


class FakeSessionRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    async def get_by_lead_id(self, lead_id: UUID) -> Session | None:
        del lead_id
        return self._session

    async def upsert(self, session: Session) -> Session:
        self._session = session
        return session


class FakeSilencedUserRepository:
    async def is_silenced(self, phone: str) -> bool:
        del phone
        return False

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        del phone, reason, silenced_by
        return None

    async def unsilence(self, phone: str) -> None:
        del phone
        return None


class FakeTranscriptionProvider:
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes, mime_type
        return "texto"


class FakeConversationAgent:
    async def respond(
        self,
        event: InboundEvent,
        session: Session,
        conversation_history: list[ConversationEvent] | None = None,
    ) -> None:
        del event, session, conversation_history
        return None


class FakeOrchestrator:
    async def classify(self, event: InboundEvent, session: Session) -> MessageClassification:
        del event, session
        return MessageClassification(
            intent="handoff_request",
            confidence=1.0,
            fsm_event="handoff_requested",
            metadata={"handoff_response_text": "Un asesor te contactara pronto."},
        )


class FakeBranchProvider:
    def __init__(self, branches: list[Branch]) -> None:
        self._branches = branches

    def list_branches(self) -> list[Branch]:
        return self._branches

    def get_branch_by_centro(self, centro: str) -> Branch | None:
        normalized = centro.strip().casefold()
        for branch in self._branches:
            if branch.centro_sheet.strip().casefold() == normalized:
                return branch
        return None

    def get_branch_by_key(self, key: str) -> Branch | None:
        normalized = key.strip().casefold()
        for branch in self._branches:
            if branch.sucursal_key.strip().casefold() == normalized:
                return branch
        return None


def _fsm_config() -> FSMConfig:
    return FSMConfig.model_validate(
        {
            "initial_state": "idle",
            "states": {
                "idle": {
                    "description": "idle",
                    "allowed_transitions": [
                        {
                            "target": "handoff_pending",
                            "event": "handoff_requested",
                            "guard": "always",
                            "actions": [],
                        }
                    ],
                    "on_enter": [],
                    "on_exit": [],
                },
                "handoff_pending": {
                    "description": "handoff_pending",
                    "allowed_transitions": [],
                    "on_enter": [],
                    "on_exit": [],
                },
            },
        }
    )


def _event() -> InboundEvent:
    now = datetime.now(UTC)
    return InboundEvent(
        message_id="wamid-555",
        from_phone="5215550000001",
        kind=MessageKind.TEXT,
        text="Quiero hablar con un asesor",
        media_url=None,
        raw_metadata={"push_name": "Cliente Handoff"},
        received_at=now,
        sender_id="5215550000001@s.whatsapp.net",
        channel="whatsapp",
        event_type="inbound_message",
        occurred_at=now,
        metadata={},
    )


def _lead(attributes: dict[str, object]) -> LeadProfile:
    now = datetime.now(UTC)
    return LeadProfile(
        id=UUID("00000000-0000-0000-0000-000000000321"),
        external_crm_id=None,
        phone="5215550000001",
        name="Cliente Handoff",
        source="whatsapp_inbound",
        attributes=attributes,
        created_at=now,
        updated_at=now,
    )


def _session(lead_id: UUID) -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        lead_id=lead_id,
        current_state="idle",
        context={},
        created_at=now,
        updated_at=now,
        last_event_at=now,
    )


@pytest.mark.asyncio
async def test_handoff_with_identified_branch_routes_to_all_branch_phones() -> None:
    event = _event()
    lead = _lead({"sucursal_key": "queretaro", "vehiculo_interes": "Freightliner Cascadia"})
    session = _session(lead.id)
    messaging = FakeMessagingProvider(event)
    session_repo = FakeSessionRepository(session)
    handler = InboundMessageHandler(
        messaging_provider=messaging,
        conversation_event_repository=FakeConversationEventRepository(),
        lead_profile_repository=FakeLeadProfileRepository(lead),
        crm_outbox_repository=FakeCRMOutboxRepository(),
        session_repository=session_repo,
        silenced_user_repository=FakeSilencedUserRepository(),
        transcription_provider=FakeTranscriptionProvider(),
        conversation_agent=FakeConversationAgent(),
        orchestrator=FakeOrchestrator(),
        fsm_config=_fsm_config(),
        branch_provider=FakeBranchProvider(
            [
                Branch(
                    sucursal_key="queretaro",
                    display_name="Sucursal Queretaro",
                    centro_sheet="Queretaro",
                    phones=["5211111111111", "5212222222222"],
                    activa=True,
                )
            ]
        ),
    )

    await handler.handle({"payload": "x"})

    recipients = {item["to"] for item in messaging.sent_messages}
    assert "5215550000001" in recipients  # ack al cliente
    assert "5211111111111" in recipients
    assert "5212222222222" in recipients
    assert session_repo._session is not None
    assert session_repo._session.current_state == "handoff_active"


@pytest.mark.asyncio
async def test_handoff_without_branch_uses_fallback_branch() -> None:
    event = _event()
    lead = _lead({})
    session = _session(lead.id)
    messaging = FakeMessagingProvider(event)
    session_repo = FakeSessionRepository(session)
    handler = InboundMessageHandler(
        messaging_provider=messaging,
        conversation_event_repository=FakeConversationEventRepository(),
        lead_profile_repository=FakeLeadProfileRepository(lead),
        crm_outbox_repository=FakeCRMOutboxRepository(),
        session_repository=session_repo,
        silenced_user_repository=FakeSilencedUserRepository(),
        transcription_provider=FakeTranscriptionProvider(),
        conversation_agent=FakeConversationAgent(),
        orchestrator=FakeOrchestrator(),
        fsm_config=_fsm_config(),
        branch_provider=FakeBranchProvider(
            [
                Branch(
                    sucursal_key="fallback",
                    display_name="Sucursal Fallback",
                    centro_sheet="CDMX",
                    phones=["5219999999999"],
                    activa=True,
                )
            ]
        ),
    )

    await handler.handle({"payload": "x"})

    branch_messages = [item for item in messaging.sent_messages if item["to"] == "5219999999999"]
    assert len(branch_messages) == 1
    assert "Resumen:" in branch_messages[0]["text"]
