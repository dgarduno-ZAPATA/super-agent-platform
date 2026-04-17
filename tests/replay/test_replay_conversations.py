from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.domain.classification import MessageClassification
from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.messaging import InboundEvent, MessageKind
from core.domain.session import Session
from core.fsm.schema import FSMConfig
from core.services.inbound_handler import InboundMessageHandler


class ReplayMessagingProvider:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str):
        self.sent_messages.append({"to": to, "text": text, "correlation_id": correlation_id})
        return None

    async def send_image(self, to: str, image_url: str, caption: str | None, correlation_id: str):
        del to
        del image_url
        del caption
        del correlation_id
        raise NotImplementedError

    async def send_document(self, to: str, document_url: str, filename: str, correlation_id: str):
        del to
        del document_url
        del filename
        del correlation_id
        raise NotImplementedError

    async def send_audio(self, to: str, audio_url: str, correlation_id: str):
        del to
        del audio_url
        del correlation_id
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        del message_id
        raise NotImplementedError

    def parse_inbound_event(self, raw_payload: dict[str, object]) -> InboundEvent:
        text = str(raw_payload.get("text", ""))
        index = str(raw_payload.get("index", "1"))
        now = datetime.now(UTC)
        return InboundEvent(
            message_id=f"replay-{index}",
            from_phone="5214425550001",
            kind=MessageKind.TEXT,
            text=text,
            media_url=None,
            raw_metadata={"push_name": "Replay Lead"},
            received_at=now,
            sender_id="5214425550001@s.whatsapp.net",
            channel="whatsapp",
            event_type="inbound_message",
            occurred_at=now,
            metadata={"source": "replay"},
        )


class ReplayConversationEventRepository:
    def __init__(self) -> None:
        self.events: list[ConversationEvent] = []

    async def append(self, event: ConversationEvent) -> bool:
        self.events.append(event)
        return True

    async def list_by_conversation(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[ConversationEvent]:
        return [item for item in self.events if item.conversation_id == conversation_id][:limit]


class ReplayLeadProfileRepository:
    def __init__(self) -> None:
        self.by_phone: dict[str, LeadProfile] = {}

    async def get_by_phone(self, phone: str) -> LeadProfile | None:
        return self.by_phone.get(phone)

    async def upsert_by_phone(self, profile: LeadProfile) -> LeadProfile:
        self.by_phone[profile.phone] = profile
        return profile


class ReplaySessionRepository:
    def __init__(self) -> None:
        self.by_lead_id: dict[UUID, Session] = {}

    async def get_by_lead_id(self, lead_id: UUID) -> Session | None:
        return self.by_lead_id.get(lead_id)

    async def upsert(self, session: Session) -> Session:
        self.by_lead_id[session.lead_id] = session
        return session

    async def update_state(
        self, session_id: UUID, new_state: str, context: dict[str, object]
    ) -> None:
        del session_id
        del new_state
        del context
        raise NotImplementedError

    async def count_not_in_states(self, states: set[str]) -> int:
        del states
        raise NotImplementedError

    async def count_by_state(self, state: str) -> int:
        del state
        raise NotImplementedError


class ReplayCRMOutboxRepository:
    async def enqueue_operation(
        self, aggregate_id: str, operation: str, payload: dict[str, object]
    ) -> UUID:
        del aggregate_id
        del operation
        del payload
        return uuid4()

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

    async def count_dlq_items(self) -> int:
        raise NotImplementedError


class ReplaySilencedRepository:
    async def is_silenced(self, phone: str) -> bool:
        del phone
        return False

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        del phone
        del reason
        del silenced_by
        raise NotImplementedError

    async def unsilence(self, phone: str) -> None:
        del phone
        raise NotImplementedError


class ReplayTranscriptionProvider:
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes
        del mime_type
        return "not-used"


class ReplayConversationAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(self, event: InboundEvent, session: Session) -> None:
        del event
        del session
        self.calls += 1


class ReplayOrchestrator:
    async def classify(self, event: InboundEvent, session: Session) -> MessageClassification:
        del session
        if event.text and "asesor" in event.text.lower():
            return MessageClassification(
                intent="handoff_request",
                confidence=1.0,
                fsm_event="handoff_requested",
                metadata={"handoff_response_text": "Te conecto con un asesor."},
            )
        return MessageClassification(
            intent="conversation",
            confidence=0.8,
            fsm_event="user_message",
            metadata={},
        )


def _build_fsm_config() -> FSMConfig:
    return FSMConfig.model_validate(
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


@pytest.mark.asyncio
async def test_basic_discovery_flow_replay() -> None:
    messaging = ReplayMessagingProvider()
    event_repo = ReplayConversationEventRepository()
    lead_repo = ReplayLeadProfileRepository()
    session_repo = ReplaySessionRepository()
    handler = InboundMessageHandler(
        messaging_provider=messaging,
        conversation_event_repository=event_repo,
        lead_profile_repository=lead_repo,
        crm_outbox_repository=ReplayCRMOutboxRepository(),
        session_repository=session_repo,
        silenced_user_repository=ReplaySilencedRepository(),
        transcription_provider=ReplayTranscriptionProvider(),
        conversation_agent=ReplayConversationAgent(),
        orchestrator=ReplayOrchestrator(),
        fsm_config=_build_fsm_config(),
    )

    sequence = [
        {"index": 1, "text": "Hola"},
        {"index": 2, "text": "Busco un camion"},
        {"index": 3, "text": "Quiero hablar con un asesor"},
    ]

    for payload in sequence:
        result = await handler.handle(payload)
        assert result.processed is True

    assert len(lead_repo.by_phone) == 1
    lead = lead_repo.by_phone["5214425550001"]
    final_session = session_repo.by_lead_id[lead.id]
    assert final_session.current_state == "handoff_pending"
