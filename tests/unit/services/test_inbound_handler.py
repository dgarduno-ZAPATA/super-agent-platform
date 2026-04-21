from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from core.domain.branch import Branch
from core.domain.classification import MessageClassification
from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.messaging import (
    InboundEvent,
    InvalidInboundPayloadError,
    MessageDeliveryReceipt,
    MessageKind,
)
from core.domain.session import Session
from core.fsm.schema import FSMConfig
from core.ports.messaging_provider import MessagingProvider
from core.services.inbound_handler import InboundMessageHandler


class FakeMessagingProvider(MessagingProvider):
    def __init__(self, event: InboundEvent | None = None, error: Exception | None = None) -> None:
        self._event = event
        self._error = error
        self.sent_messages: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        self.sent_messages.append(
            {
                "to": to,
                "text": text,
                "correlation_id": correlation_id,
            }
        )
        return MessageDeliveryReceipt(
            message_id="out-001",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        raise NotImplementedError

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        raise NotImplementedError

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        raise NotImplementedError

    def parse_inbound_event(self, raw_payload: dict[str, object]) -> InboundEvent:
        if self._error is not None:
            raise self._error
        if self._event is None:
            raise AssertionError("FakeMessagingProvider requires event or error")
        return self._event


class FakeConversationEventRepository:
    def __init__(self) -> None:
        self.events: list[ConversationEvent] = []
        self._message_ids: set[str] = set()

    async def append(self, event: ConversationEvent) -> bool:
        if event.message_id is not None and event.message_id in self._message_ids:
            return False

        if event.message_id is not None:
            self._message_ids.add(event.message_id)

        self.events.append(event)
        return True

    async def list_by_conversation(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[ConversationEvent]:
        return [item for item in self.events if item.conversation_id == conversation_id][:limit]


class FakeLeadProfileRepository:
    def __init__(self) -> None:
        self.by_phone: dict[str, LeadProfile] = {}
        self.upsert_calls = 0

    async def get_by_phone(self, phone: str) -> LeadProfile | None:
        return self.by_phone.get(phone)

    async def upsert_by_phone(self, profile: LeadProfile) -> LeadProfile:
        self.upsert_calls += 1
        existing = self.by_phone.get(profile.phone)
        if existing is None:
            self.by_phone[profile.phone] = profile
            return profile

        updated = existing.model_copy(
            update={
                "name": profile.name,
                "source": profile.source,
                "attributes": profile.attributes,
            }
        )
        self.by_phone[profile.phone] = updated
        return updated


class FakeSessionRepository:
    def __init__(self) -> None:
        self.by_lead_id: dict[UUID, Session] = {}
        self.upsert_calls = 0

    async def get_by_lead_id(self, lead_id: UUID) -> Session | None:
        return self.by_lead_id.get(lead_id)

    async def upsert(self, session: Session) -> Session:
        self.upsert_calls += 1
        self.by_lead_id[session.lead_id] = session
        return session

    async def update_state(
        self, session_id: UUID, new_state: str, context: dict[str, object]
    ) -> None:
        raise NotImplementedError


class FakeCRMOutboxRepository:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []

    async def enqueue_operation(
        self, aggregate_id: str, operation: str, payload: dict[str, object]
    ) -> UUID:
        item_id = UUID("00000000-0000-0000-0000-000000000001")
        self.enqueued.append(
            {
                "id": item_id,
                "aggregate_id": aggregate_id,
                "operation": operation,
                "payload": payload,
            }
        )
        return item_id

    async def get_pending_batch(self, limit: int = 10):
        del limit
        raise NotImplementedError

    async def mark_as_done(self, item_id: UUID) -> None:
        del item_id
        raise NotImplementedError

    async def mark_as_failed_with_retry(
        self, item_id: UUID, error: str, next_retry_at: datetime, attempt: int
    ) -> None:
        del item_id
        del error
        del next_retry_at
        del attempt
        raise NotImplementedError

    async def move_to_dlq(self, item_id: UUID, error: str) -> None:
        del item_id
        del error
        raise NotImplementedError


class FakeSilencedUserRepository:
    def __init__(self, silenced_phones: set[str] | None = None) -> None:
        self.silenced_phones = silenced_phones or set()
        self.silence_calls: list[tuple[str, str, str]] = []

    async def is_silenced(self, phone: str) -> bool:
        return phone in self.silenced_phones

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        self.silenced_phones.add(phone)
        self.silence_calls.append((phone, reason, silenced_by))

    async def unsilence(self, phone: str) -> None:
        self.silenced_phones.discard(phone)


class FakeTranscriptionProvider:
    def __init__(self, transcription_text: str = "Transcribed audio") -> None:
        self.transcription_text = transcription_text
        self.calls: list[tuple[bytes, str]] = []

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        self.calls.append((audio_bytes, mime_type))
        return self.transcription_text


class FakeConversationAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[InboundEvent, Session]] = []

    async def respond(self, event: InboundEvent, session: Session) -> None:
        self.calls.append((event, session))


class FakeOrchestrator:
    def __init__(
        self,
        intent: str = "conversation",
        fsm_event: str = "user_message",
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.intent = intent
        self.fsm_event = fsm_event
        self.metadata = metadata or {}
        self.calls = 0

    async def classify(self, event: InboundEvent, session: Session) -> MessageClassification:
        del event
        del session
        self.calls += 1
        return MessageClassification(
            intent=self.intent,  # type: ignore[arg-type]
            confidence=1.0 if self.intent in {"opt_out", "handoff_request", "unsupported"} else 0.8,
            fsm_event=self.fsm_event,
            metadata=self.metadata,
        )


class FakeBranchProvider:
    def __init__(self, branches: list[Branch] | None = None) -> None:
        self.branches = branches or []

    def list_branches(self) -> list[Branch]:
        return self.branches

    def get_branch_by_centro(self, centro: str) -> Branch | None:
        normalized = centro.strip().casefold()
        for branch in self.branches:
            if branch.centro_sheet.strip().casefold() == normalized:
                return branch
        return None

    def get_branch_by_key(self, key: str) -> Branch | None:
        normalized = key.strip().casefold()
        for branch in self.branches:
            if branch.sucursal_key.strip().casefold() == normalized:
                return branch
        return None


def _build_event(kind: MessageKind = MessageKind.TEXT) -> InboundEvent:
    return InboundEvent(
        message_id="wamid-001",
        from_phone="5214421234567",
        kind=kind,
        text="Hola" if kind is MessageKind.TEXT else None,
        media_url="https://cdn.example.com/audio.ogg" if kind is MessageKind.AUDIO else None,
        raw_metadata={"push_name": "Cliente Demo"},
        received_at=datetime.now(UTC),
        sender_id="5214421234567@s.whatsapp.net",
        channel="whatsapp",
        event_type="inbound_message",
        occurred_at=datetime.now(UTC),
        metadata={"source": "unit-test"},
    )


def _build_handler(
    messaging_provider: MessagingProvider,
    event_repo: FakeConversationEventRepository,
    lead_repo: FakeLeadProfileRepository,
    crm_outbox_repo: FakeCRMOutboxRepository,
    session_repo: FakeSessionRepository,
    silenced_repo: FakeSilencedUserRepository,
    transcription_provider: FakeTranscriptionProvider,
    conversation_agent: FakeConversationAgent,
    orchestrator: FakeOrchestrator | None = None,
    branch_provider: FakeBranchProvider | None = None,
) -> InboundMessageHandler:
    fsm_config = FSMConfig.model_validate(
        {
            "initial_state": "idle",
            "states": {
                "idle": {
                    "description": "idle",
                    "allowed_transitions": [
                        {
                            "target": "greeting",
                            "event": "user_message",
                            "guard": "always",
                            "actions": [],
                        },
                        {
                            "target": "cooldown",
                            "event": "opt_out_detected",
                            "guard": "always",
                            "actions": [],
                        },
                        {
                            "target": "handoff_pending",
                            "event": "handoff_requested",
                            "guard": "always",
                            "actions": [],
                        },
                    ],
                    "on_enter": [],
                    "on_exit": [],
                },
                "greeting": {
                    "description": "greeting",
                    "allowed_transitions": [],
                    "on_enter": [],
                    "on_exit": [],
                },
                "handoff_pending": {
                    "description": "handoff_pending",
                    "allowed_transitions": [],
                    "on_enter": [],
                    "on_exit": [],
                },
                "cooldown": {
                    "description": "cooldown",
                    "allowed_transitions": [],
                    "on_enter": [],
                    "on_exit": [],
                },
            },
        }
    )

    return InboundMessageHandler(
        messaging_provider=messaging_provider,
        conversation_event_repository=event_repo,
        lead_profile_repository=lead_repo,
        crm_outbox_repository=crm_outbox_repo,
        session_repository=session_repo,
        silenced_user_repository=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
        orchestrator=orchestrator or FakeOrchestrator(),
        fsm_config=fsm_config,
        branch_provider=branch_provider or FakeBranchProvider(),
    )


@pytest.mark.asyncio
async def test_text_message_persists_event_and_creates_lead_and_session() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    conversation_agent = FakeConversationAgent()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.TEXT)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
    )

    result = await handler.handle({"any": "payload"})

    assert result.processed is True
    assert len(event_repo.events) == 1
    assert lead_repo.by_phone["5214421234567"].phone == "5214421234567"
    assert len(session_repo.by_lead_id) == 1
    persisted_session = next(iter(session_repo.by_lead_id.values()))
    assert persisted_session.current_state == "greeting"
    assert persisted_session.context["last_inbound_message"]["type"] == "text"
    assert len(conversation_agent.calls) == 1
    assert len(crm_outbox_repo.enqueued) == 1
    assert crm_outbox_repo.enqueued[0]["operation"] == "upsert_lead"


@pytest.mark.asyncio
async def test_duplicate_message_is_ignored_by_dedup() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    conversation_agent = FakeConversationAgent()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.TEXT)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
    )

    first = await handler.handle({"payload": 1})
    second = await handler.handle({"payload": 2})

    assert first.processed is True
    assert second.processed is False
    assert second.status == "duplicate"
    assert len(event_repo.events) == 1
    assert lead_repo.upsert_calls == 1
    assert session_repo.upsert_calls == 2
    assert len(conversation_agent.calls) == 1


@pytest.mark.asyncio
async def test_silenced_phone_is_ignored_without_processing() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository(silenced_phones={"5214421234567"})
    transcription_provider = FakeTranscriptionProvider()
    conversation_agent = FakeConversationAgent()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.TEXT)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
    )

    result = await handler.handle({"any": "payload"})

    assert result.processed is False
    assert result.status == "silenced"
    assert len(event_repo.events) == 0
    assert lead_repo.upsert_calls == 0
    assert session_repo.upsert_calls == 0
    assert len(conversation_agent.calls) == 0


@pytest.mark.asyncio
async def test_group_payload_is_ignored_without_crashing() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    conversation_agent = FakeConversationAgent()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(
            error=InvalidInboundPayloadError("invalid inbound sender: group")
        ),
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
    )

    result = await handler.handle({"any": "payload"})

    assert result.processed is False
    assert result.status == "invalid_payload"
    assert len(event_repo.events) == 0
    assert lead_repo.upsert_calls == 0
    assert session_repo.upsert_calls == 0
    assert len(conversation_agent.calls) == 0


@pytest.mark.asyncio
async def test_audio_message_calls_transcription_provider() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider("Texto transcrito")
    conversation_agent = FakeConversationAgent()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.AUDIO)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
    )

    result = await handler.handle({"audio": True})

    assert result.processed is True
    assert len(transcription_provider.calls) == 1
    assert event_repo.events[0].payload["transcription_text"] == "Texto transcrito"
    assert len(conversation_agent.calls) == 1


@pytest.mark.asyncio
async def test_opt_out_message_silences_user_and_skips_responder() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    conversation_agent = FakeConversationAgent()
    provider = FakeMessagingProvider(event=_build_event(MessageKind.TEXT))
    handler = _build_handler(
        messaging_provider=provider,
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
        orchestrator=FakeOrchestrator(
            intent="opt_out",
            fsm_event="opt_out_detected",
            metadata={"matched_keyword": "stop"},
        ),
    )

    result = await handler.handle({"text": "STOP"})

    assert result.processed is True
    assert len(silenced_repo.silence_calls) == 1
    assert len(conversation_agent.calls) == 0
    assert provider.sent_messages == []


@pytest.mark.asyncio
async def test_handoff_request_sends_handoff_ack_and_skips_echo() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    conversation_agent = FakeConversationAgent()
    provider = FakeMessagingProvider(event=_build_event(MessageKind.TEXT))
    handler = _build_handler(
        messaging_provider=provider,
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
        orchestrator=FakeOrchestrator(
            intent="handoff_request",
            fsm_event="handoff_requested",
            metadata={"handoff_response_text": "Un asesor te contactara pronto."},
        ),
    )

    result = await handler.handle({"text": "asesor"})

    assert result.processed is True
    assert len(provider.sent_messages) == 1
    assert provider.sent_messages[0]["text"] == "Un asesor te contactara pronto."
    assert len(conversation_agent.calls) == 0


@pytest.mark.asyncio
async def test_handoff_active_session_persists_event_and_skips_bot_processing() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    crm_outbox_repo = FakeCRMOutboxRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    conversation_agent = FakeConversationAgent()
    orchestrator = FakeOrchestrator()
    provider = FakeMessagingProvider(event=_build_event(MessageKind.TEXT))

    now = datetime.now(UTC)
    lead = LeadProfile(
        id=UUID("00000000-0000-0000-0000-000000000123"),
        external_crm_id=None,
        phone="5214421234567",
        name="Cliente Demo",
        source="whatsapp_inbound",
        attributes={},
        created_at=now,
        updated_at=now,
    )
    lead_repo.by_phone[lead.phone] = lead
    session_repo.by_lead_id[lead.id] = Session(
        id=UUID("00000000-0000-0000-0000-000000000456"),
        lead_id=lead.id,
        current_state="handoff_active",
        context={"owner": "human_agent"},
        created_at=now,
        updated_at=now,
        last_event_at=now,
    )

    handler = _build_handler(
        messaging_provider=provider,
        event_repo=event_repo,
        lead_repo=lead_repo,
        crm_outbox_repo=crm_outbox_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
        orchestrator=orchestrator,
    )

    result = await handler.handle({"text": "sigo aqui"})

    assert result.processed is True
    assert result.status == "handoff_active"
    assert len(event_repo.events) == 1
    assert len(crm_outbox_repo.enqueued) == 0
    assert orchestrator.calls == 0
    assert len(conversation_agent.calls) == 0
