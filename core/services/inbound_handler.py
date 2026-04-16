from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import structlog

from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.messaging import (
    InboundEvent,
    InvalidInboundPayloadError,
    MessageKind,
    UnsupportedEventTypeError,
)
from core.domain.session import Session
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import (
    ConversationEventRepository,
    LeadProfileRepository,
    SessionRepository,
    SilencedUserRepository,
)
from core.ports.transcription_provider import TranscriptionProvider
from core.services.responder import EchoResponder

logger = structlog.get_logger("super_agent_platform.core.services.inbound_handler")


@dataclass(frozen=True, slots=True)
class InboundHandleResult:
    status: str
    processed: bool
    conversation_id: UUID | None = None
    lead_id: UUID | None = None
    event_type: str | None = None
    message_kind: MessageKind | None = None


class InboundMessageHandler:
    def __init__(
        self,
        messaging_provider: MessagingProvider,
        conversation_event_repository: ConversationEventRepository,
        lead_profile_repository: LeadProfileRepository,
        session_repository: SessionRepository,
        silenced_user_repository: SilencedUserRepository,
        transcription_provider: TranscriptionProvider,
        responder: EchoResponder,
    ) -> None:
        self._messaging_provider = messaging_provider
        self._conversation_event_repository = conversation_event_repository
        self._lead_profile_repository = lead_profile_repository
        self._session_repository = session_repository
        self._silenced_user_repository = silenced_user_repository
        self._transcription_provider = transcription_provider
        self._responder = responder

    async def handle(self, raw_payload: dict[str, object]) -> InboundHandleResult:
        try:
            inbound_event = self._messaging_provider.parse_inbound_event(raw_payload)
        except (InvalidInboundPayloadError, UnsupportedEventTypeError) as exc:
            logger.info("inbound_webhook_ignored_invalid_payload", reason=str(exc))
            return InboundHandleResult(status="invalid_payload", processed=False)

        if await self._silenced_user_repository.is_silenced(inbound_event.from_phone):
            logger.info(
                "inbound_webhook_ignored_silenced_user",
                phone=inbound_event.from_phone,
                message_id=inbound_event.message_id,
            )
            return InboundHandleResult(
                status="silenced",
                processed=False,
                message_kind=inbound_event.kind,
                event_type=inbound_event.event_type,
            )

        enriched_inbound_event = self._enrich_event_for_processing(inbound_event)
        conversation_id = self._build_conversation_id(enriched_inbound_event.from_phone)
        event_payload = self._build_event_payload(enriched_inbound_event)
        conversation_event = ConversationEvent(
            id=uuid4(),
            conversation_id=conversation_id,
            lead_id=None,
            event_type=enriched_inbound_event.event_type,
            payload=event_payload,
            created_at=enriched_inbound_event.received_at,
            message_id=enriched_inbound_event.message_id,
        )

        appended = await self._conversation_event_repository.append(conversation_event)
        if not appended:
            logger.info(
                "inbound_webhook_ignored_duplicate",
                conversation_id=str(conversation_id),
                message_id=enriched_inbound_event.message_id,
                event_type=enriched_inbound_event.event_type,
                message_kind=enriched_inbound_event.kind.value,
            )
            return InboundHandleResult(
                status="duplicate",
                processed=False,
                conversation_id=conversation_id,
                event_type=enriched_inbound_event.event_type,
                message_kind=enriched_inbound_event.kind,
            )

        lead_profile = await self._get_or_create_lead_profile(enriched_inbound_event)
        session, created = await self._get_or_create_session(
            lead_profile.id, enriched_inbound_event.received_at
        )

        await self._responder.respond(enriched_inbound_event, session)
        await self._update_session_after_response(
            session=session,
            inbound_event=enriched_inbound_event,
            is_first_contact=created,
        )

        logger.info(
            "inbound_webhook_processed",
            conversation_id=str(conversation_id),
            lead_id=str(lead_profile.id),
            event_type=enriched_inbound_event.event_type,
            message_kind=enriched_inbound_event.kind.value,
        )
        return InboundHandleResult(
            status="processed",
            processed=True,
            conversation_id=conversation_id,
            lead_id=lead_profile.id,
            event_type=enriched_inbound_event.event_type,
            message_kind=enriched_inbound_event.kind,
        )

    async def _get_or_create_lead_profile(self, inbound_event: InboundEvent) -> LeadProfile:
        existing = await self._lead_profile_repository.get_by_phone(inbound_event.from_phone)
        if existing is not None:
            return existing

        now = datetime.now(UTC)
        push_name = inbound_event.raw_metadata.get("push_name")
        lead_name = push_name if isinstance(push_name, str) and push_name else None

        return await self._lead_profile_repository.upsert_by_phone(
            LeadProfile(
                id=uuid4(),
                external_crm_id=None,
                phone=inbound_event.from_phone,
                name=lead_name,
                source="whatsapp_inbound",
                attributes={
                    "channel": inbound_event.channel,
                    "sender_id": inbound_event.sender_id,
                },
                created_at=now,
                updated_at=now,
            )
        )

    async def _get_or_create_session(
        self, lead_id: UUID, occurred_at: datetime
    ) -> tuple[Session, bool]:
        existing = await self._session_repository.get_by_lead_id(lead_id)
        if existing is not None:
            return existing, False

        now = datetime.now(UTC)
        created = await self._session_repository.upsert(
            Session(
                id=uuid4(),
                lead_id=lead_id,
                current_state="new_lead",
                context={},
                created_at=now,
                updated_at=now,
                last_event_at=occurred_at,
            )
        )
        return created, True

    async def _update_session_after_response(
        self,
        session: Session,
        inbound_event: InboundEvent,
        is_first_contact: bool,
    ) -> Session:
        now = datetime.now(UTC)
        new_context = dict(session.context)
        new_context["last_inbound_message"] = {
            "text": inbound_event.text,
            "type": inbound_event.kind.value,
            "timestamp": inbound_event.received_at.isoformat(),
        }

        updated_session = Session(
            id=session.id,
            lead_id=session.lead_id,
            current_state="greeting" if is_first_contact else session.current_state,
            context=new_context,
            created_at=session.created_at,
            updated_at=now,
            last_event_at=inbound_event.received_at,
        )
        return await self._session_repository.upsert(updated_session)

    def _enrich_event_for_processing(self, inbound_event: InboundEvent) -> InboundEvent:
        if inbound_event.kind is not MessageKind.AUDIO:
            return inbound_event

        transcription_text = self._transcribe_audio(inbound_event)
        metadata = dict(inbound_event.metadata)
        metadata["transcription_text"] = transcription_text

        return replace(
            inbound_event,
            text=transcription_text if inbound_event.text is None else inbound_event.text,
            metadata=metadata,
        )

    def _build_event_payload(self, inbound_event: InboundEvent) -> dict[str, object]:
        payload: dict[str, object] = {
            "message_id": inbound_event.message_id,
            "from_phone": inbound_event.from_phone,
            "message_kind": inbound_event.kind.value,
            "text": inbound_event.text,
            "media_url": inbound_event.media_url,
            "channel": inbound_event.channel,
            "event_type": inbound_event.event_type,
            "sender_id": inbound_event.sender_id,
            "metadata": inbound_event.metadata,
            "raw_metadata": inbound_event.raw_metadata,
        }

        if inbound_event.occurred_at is not None:
            payload["occurred_at"] = inbound_event.occurred_at.isoformat()

        transcription_text = inbound_event.metadata.get("transcription_text")
        if inbound_event.kind is MessageKind.AUDIO and isinstance(transcription_text, str):
            payload["transcription_text"] = transcription_text

        return payload

    def _transcribe_audio(self, inbound_event: InboundEvent) -> str:
        mime_type = self._guess_audio_mime_type(inbound_event.media_url)

        try:
            return self._transcription_provider.transcribe(audio_bytes=b"", mime_type=mime_type)
        except Exception:
            logger.warning(
                "inbound_audio_transcription_failed",
                message_id=inbound_event.message_id,
                mime_type=mime_type,
            )
            return "Audio transcription pending"

    @staticmethod
    def _build_conversation_id(phone: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"whatsapp:{phone}")

    @staticmethod
    def _guess_audio_mime_type(media_url: str | None) -> str:
        if media_url is None:
            return "audio/ogg"

        suffix = Path(media_url).suffix.lower()
        if suffix in {".ogg", ".opus"}:
            return "audio/ogg"
        if suffix == ".mp3":
            return "audio/mpeg"
        if suffix == ".wav":
            return "audio/wav"
        if suffix == ".m4a":
            return "audio/mp4"
        return "audio/ogg"
