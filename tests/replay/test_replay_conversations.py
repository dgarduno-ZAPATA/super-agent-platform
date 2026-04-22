from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.domain.branch import Branch
from core.domain.classification import MessageClassification
from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.messaging import InboundEvent, MessageKind
from core.domain.session import Session
from core.fsm.schema import FSMConfig
from core.services.inbound_handler import InboundMessageHandler
from core.services.replay_engine import ReplayEngine


class ReplayMessagingProvider:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str):
        self.sent_messages.append({"to": to, "text": text, "correlation_id": correlation_id})
        return None

    async def send_image(self, to: str, image_url: str, caption: str | None, correlation_id: str):
        del to, image_url, caption, correlation_id
        raise NotImplementedError

    async def send_document(self, to: str, document_url: str, filename: str, correlation_id: str):
        del to, document_url, filename, correlation_id
        raise NotImplementedError

    async def send_audio(self, to: str, audio_url: str, correlation_id: str):
        del to, audio_url, correlation_id
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

    async def list_by_lead_id(self, lead_id: UUID, limit: int = 1000) -> list[ConversationEvent]:
        return [item for item in self.events if item.lead_id == lead_id][:limit]


class ReplayLeadProfileRepository:
    def __init__(self) -> None:
        self.by_phone: dict[str, LeadProfile] = {}

    async def get_by_id(self, lead_id: UUID) -> LeadProfile | None:
        for item in self.by_phone.values():
            if item.id == lead_id:
                return item
        return None

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
        del session_id, new_state, context
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
        del aggregate_id, operation, payload
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
        del item_id, error, next_retry_at, attempt
        raise NotImplementedError

    async def move_to_dlq(self, item_id: UUID, error: str) -> None:
        del item_id, error
        raise NotImplementedError

    async def count_dlq_items(self) -> int:
        raise NotImplementedError

    async def count_pending_items(self) -> int:
        raise NotImplementedError


class ReplaySilencedRepository:
    async def is_silenced(self, phone: str) -> bool:
        del phone
        return False

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        del phone, reason, silenced_by
        raise NotImplementedError

    async def unsilence(self, phone: str) -> None:
        del phone
        raise NotImplementedError


class ReplayTranscriptionProvider:
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes, mime_type
        return "not-used"


class ReplayConversationAgent:
    async def respond(
        self,
        event: InboundEvent,
        session: Session,
        conversation_history: list[ConversationEvent] | None = None,
    ) -> None:
        del event, session, conversation_history


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


class ReplayBranchProvider:
    def __init__(self) -> None:
        self._branches = [
            Branch(
                sucursal_key="fallback",
                display_name="Sucursal Fallback",
                centro_sheet="CDMX",
                phones=["5215511111111"],
                activa=True,
            )
        ]

    def list_branches(self) -> list[Branch]:
        return self._branches

    def get_branch_by_centro(self, centro: str) -> Branch | None:
        del centro
        return None

    def get_branch_by_key(self, key: str) -> Branch | None:
        del key
        return None


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


async def _run_sequence() -> tuple[
    ReplayConversationEventRepository,
    ReplayLeadProfileRepository,
    ReplaySessionRepository,
    UUID,
]:
    event_repo = ReplayConversationEventRepository()
    lead_repo = ReplayLeadProfileRepository()
    session_repo = ReplaySessionRepository()
    handler = InboundMessageHandler(
        messaging_provider=ReplayMessagingProvider(),
        conversation_event_repository=event_repo,
        lead_profile_repository=lead_repo,
        crm_outbox_repository=ReplayCRMOutboxRepository(),
        session_repository=session_repo,
        silenced_user_repository=ReplaySilencedRepository(),
        transcription_provider=ReplayTranscriptionProvider(),
        conversation_agent=ReplayConversationAgent(),
        orchestrator=ReplayOrchestrator(),
        fsm_config=_build_fsm_config(),
        branch_provider=ReplayBranchProvider(),
    )

    sequence = [
        {"index": 1, "text": "Hola"},
        {"index": 2, "text": "Busco un camion"},
        {"index": 3, "text": "Quiero hablar con un asesor"},
    ]

    for payload in sequence:
        result = await handler.handle(payload)
        assert result.processed is True

    lead = lead_repo.by_phone["5214425550001"]
    return event_repo, lead_repo, session_repo, lead.id


@pytest.mark.asyncio
async def test_basic_discovery_flow_replay() -> None:
    event_repo, lead_repo, session_repo, lead_id = await _run_sequence()
    engine = ReplayEngine(
        lead_profile_repository=lead_repo,
        session_repository=session_repo,
        event_repository=event_repo,
        fsm_config=_build_fsm_config(),
        handoff_keywords=["asesor"],
        opt_out_keywords=["stop"],
    )

    replay = await engine.replay_conversation(lead_id=lead_id, dry_run=True)

    assert replay["final_state"] == "handoff_pending"
    assert replay["events_processed"] >= 3


@pytest.mark.asyncio
async def test_replay_stops_at_event_id() -> None:
    event_repo, lead_repo, session_repo, lead_id = await _run_sequence()
    target_event_id = event_repo.events[1].id
    engine = ReplayEngine(
        lead_profile_repository=lead_repo,
        session_repository=session_repo,
        event_repository=event_repo,
        fsm_config=_build_fsm_config(),
        handoff_keywords=["asesor"],
        opt_out_keywords=["stop"],
    )

    replay = await engine.replay_conversation(
        lead_id=lead_id,
        until_event_id=target_event_id,
        dry_run=True,
    )

    assert replay["events_processed"] == 2
    assert replay["transitions"][-1]["event_id"] == str(target_event_id)


@pytest.mark.asyncio
async def test_trace_summary_counts_are_correct() -> None:
    event_repo, lead_repo, session_repo, lead_id = await _run_sequence()
    engine = ReplayEngine(
        lead_profile_repository=lead_repo,
        session_repository=session_repo,
        event_repository=event_repo,
        fsm_config=_build_fsm_config(),
        handoff_keywords=["asesor"],
        opt_out_keywords=["stop"],
    )

    trace = await engine.build_trace(lead_id=lead_id)

    summary = trace["summary"]
    assert summary["inbound_count"] >= 3
    assert summary["handoff_count"] >= 1
    assert summary["fsm_transitions"] >= 1
