from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.messaging import (
    InboundEvent,
    InvalidInboundPayloadError,
    MessageDeliveryReceipt,
    MessageKind,
)
from core.domain.session import Session
from core.ports.messaging_provider import MessagingProvider
from core.services.inbound_handler import InboundMessageHandler


class FakeMessagingProvider(MessagingProvider):
    def __init__(self, event: InboundEvent | None = None, error: Exception | None = None) -> None:
        self._event = event
        self._error = error

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        raise NotImplementedError

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


class FakeSilencedUserRepository:
    def __init__(self, silenced_phones: set[str] | None = None) -> None:
        self.silenced_phones = silenced_phones or set()

    async def is_silenced(self, phone: str) -> bool:
        return phone in self.silenced_phones

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        self.silenced_phones.add(phone)

    async def unsilence(self, phone: str) -> None:
        self.silenced_phones.discard(phone)


class FakeTranscriptionProvider:
    def __init__(self, transcription_text: str = "Transcribed audio") -> None:
        self.transcription_text = transcription_text
        self.calls: list[tuple[bytes, str]] = []

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        self.calls.append((audio_bytes, mime_type))
        return self.transcription_text


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
    session_repo: FakeSessionRepository,
    silenced_repo: FakeSilencedUserRepository,
    transcription_provider: FakeTranscriptionProvider,
) -> InboundMessageHandler:
    return InboundMessageHandler(
        messaging_provider=messaging_provider,
        conversation_event_repository=event_repo,
        lead_profile_repository=lead_repo,
        session_repository=session_repo,
        silenced_user_repository=silenced_repo,
        transcription_provider=transcription_provider,
    )


@pytest.mark.asyncio
async def test_text_message_persists_event_and_creates_lead_and_session() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.TEXT)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
    )

    result = await handler.handle({"any": "payload"})

    assert result.processed is True
    assert len(event_repo.events) == 1
    assert lead_repo.by_phone["5214421234567"].phone == "5214421234567"
    assert len(session_repo.by_lead_id) == 1


@pytest.mark.asyncio
async def test_duplicate_message_is_ignored_by_dedup() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.TEXT)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
    )

    first = await handler.handle({"payload": 1})
    second = await handler.handle({"payload": 2})

    assert first.processed is True
    assert second.processed is False
    assert second.status == "duplicate"
    assert len(event_repo.events) == 1
    assert lead_repo.upsert_calls == 1
    assert session_repo.upsert_calls == 1


@pytest.mark.asyncio
async def test_silenced_phone_is_ignored_without_processing() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository(silenced_phones={"5214421234567"})
    transcription_provider = FakeTranscriptionProvider()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.TEXT)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
    )

    result = await handler.handle({"any": "payload"})

    assert result.processed is False
    assert result.status == "silenced"
    assert len(event_repo.events) == 0
    assert lead_repo.upsert_calls == 0
    assert session_repo.upsert_calls == 0


@pytest.mark.asyncio
async def test_group_payload_is_ignored_without_crashing() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider()
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(
            error=InvalidInboundPayloadError("invalid inbound sender: group")
        ),
        event_repo=event_repo,
        lead_repo=lead_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
    )

    result = await handler.handle({"any": "payload"})

    assert result.processed is False
    assert result.status == "invalid_payload"
    assert len(event_repo.events) == 0
    assert lead_repo.upsert_calls == 0
    assert session_repo.upsert_calls == 0


@pytest.mark.asyncio
async def test_audio_message_calls_transcription_provider() -> None:
    event_repo = FakeConversationEventRepository()
    lead_repo = FakeLeadProfileRepository()
    session_repo = FakeSessionRepository()
    silenced_repo = FakeSilencedUserRepository()
    transcription_provider = FakeTranscriptionProvider("Texto transcrito")
    handler = _build_handler(
        messaging_provider=FakeMessagingProvider(event=_build_event(MessageKind.AUDIO)),
        event_repo=event_repo,
        lead_repo=lead_repo,
        session_repo=session_repo,
        silenced_repo=silenced_repo,
        transcription_provider=transcription_provider,
    )

    result = await handler.handle({"audio": True})

    assert result.processed is True
    assert len(transcription_provider.calls) == 1
    assert event_repo.events[0].payload["transcription_text"] == "Texto transcrito"
