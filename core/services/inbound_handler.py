from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sentry_sdk
import structlog

from core.brand.schema import Brand
from core.domain.branch import Branch
from core.domain.classification import MessageClassification
from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.messaging import (
    InboundEvent,
    InvalidInboundPayloadError,
    MessageKind,
    UnsupportedEventTypeError,
)
from core.domain.session import Session
from core.fsm.actions import FSMActionDependencies, build_default_action_registry
from core.fsm.engine import FSMEngine
from core.fsm.guards import build_default_guard_registry
from core.fsm.schema import FSMConfig
from core.ports.branch_provider import BranchProvider
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import (
    ConversationEventRepository,
    CRMOutboxRepository,
    LeadProfileRepository,
    SessionRepository,
    SilencedUserRepository,
)
from core.ports.transcription_provider import TranscriptionProvider
from core.services.conversation_agent import ConversationAgent
from core.services.image_analysis_service import ImageAnalysisService
from core.services.orchestrator import OrchestratorAgent

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
        crm_outbox_repository: CRMOutboxRepository,
        session_repository: SessionRepository,
        silenced_user_repository: SilencedUserRepository,
        transcription_provider: TranscriptionProvider,
        image_analysis_service: ImageAnalysisService,
        conversation_agent: ConversationAgent,
        orchestrator: OrchestratorAgent,
        fsm_config: FSMConfig,
        branch_provider: BranchProvider,
        brand: Brand | None = None,
        message_accumulation_seconds: float = 0.0,
    ) -> None:
        self._messaging_provider = messaging_provider
        self._conversation_event_repository = conversation_event_repository
        self._lead_profile_repository = lead_profile_repository
        self._crm_outbox_repository = crm_outbox_repository
        self._session_repository = session_repository
        self._silenced_user_repository = silenced_user_repository
        self._transcription_provider = transcription_provider
        self._image_analysis_service = image_analysis_service
        self._conversation_agent = conversation_agent
        self._orchestrator = orchestrator
        self._fsm_config = fsm_config
        self._branch_provider = branch_provider
        self._brand = brand
        self._message_accumulation_seconds = max(0.0, float(message_accumulation_seconds))
        self._guard_registry = build_default_guard_registry()
        self._action_registry = build_default_action_registry(
            FSMActionDependencies(
                session_repository=self._session_repository,
                crm_outbox_repository=self._crm_outbox_repository,
                messaging_provider=self._messaging_provider,
                branch_provider=self._branch_provider,
                brand=self._brand,
            )
        )

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

        enriched_inbound_event, media_failure_response = await self._enrich_event_for_processing(
            inbound_event
        )
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

        if await self._should_defer_due_newer_inbound(
            conversation_id=conversation_id,
            current_message_id=enriched_inbound_event.message_id,
        ):
            logger.info(
                "inbound_message_deferred_for_accumulation",
                conversation_id=str(conversation_id),
                message_id=enriched_inbound_event.message_id,
                accumulation_seconds=self._message_accumulation_seconds,
            )
            return InboundHandleResult(
                status="deferred_for_accumulation",
                processed=False,
                conversation_id=conversation_id,
                event_type=enriched_inbound_event.event_type,
                message_kind=enriched_inbound_event.kind,
            )

        lead_profile, _ = await self._get_or_create_lead_profile(enriched_inbound_event)
        session = await self._get_or_create_session(
            lead_profile.id, enriched_inbound_event.received_at
        )
        lead_profile = await self._update_lead_profile_from_inbound(
            lead_profile=lead_profile,
            inbound_event=enriched_inbound_event,
        )
        await self._enqueue_lead_upsert(
            lead_profile=lead_profile,
            session=session,
            inbound_event=enriched_inbound_event,
            context_source="inbound_pre_fsm",
        )
        self._set_sentry_tags(
            lead_id=lead_profile.id,
            conversation_id=conversation_id,
            fsm_state=session.current_state,
        )
        if session.current_state == "handoff_active":
            logger.info(
                "inbound_webhook_handoff_active_bot_silenced",
                conversation_id=str(conversation_id),
                lead_id=str(lead_profile.id),
                message_id=enriched_inbound_event.message_id,
                event_type=enriched_inbound_event.event_type,
            )
            return InboundHandleResult(
                status="handoff_active",
                processed=True,
                conversation_id=conversation_id,
                lead_id=lead_profile.id,
                event_type=enriched_inbound_event.event_type,
                message_kind=enriched_inbound_event.kind,
            )

        if media_failure_response is not None:
            await self._send_media_processing_failure_response(
                inbound_event=enriched_inbound_event,
                response_text=media_failure_response,
            )
            logger.info(
                "inbound_webhook_processed_media_fallback",
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

        classification = await self._orchestrator.classify(enriched_inbound_event, session)
        resolved_state = self._resolve_session_state(session.current_state)
        fsm_context = self._build_fsm_context(
            inbound_event=enriched_inbound_event,
            lead_profile=lead_profile,
            session=session,
            classification=classification,
        )

        fsm_engine = FSMEngine(
            config=self._fsm_config,
            current_state=resolved_state,
            guard_registry=self._guard_registry,
            action_registry=self._action_registry,
        )
        transition_result = await fsm_engine.process_event(classification.fsm_event, fsm_context)
        response_text = (
            str(classification.metadata.get("handoff_response_text"))
            if isinstance(classification.metadata.get("handoff_response_text"), str)
            else None
        )
        response_chars = len(response_text) if response_text is not None else None
        # TODO: plumb concrete tool-call names from the LLM turn into this handler log.
        tool_calls_made = classification.metadata.get("tool_calls")
        if not isinstance(tool_calls_made, list):
            tool_calls_made = []
        else:
            tool_calls_made = [str(item) for item in tool_calls_made]
        logger.info(
            "fsm_event_processed",
            session_id=str(session.id),
            lead_id=str(lead_profile.id),
            intent=classification.intent,
            fsm_event=classification.fsm_event,
            old_state=transition_result.old_state,
            new_state=transition_result.new_state,
            transition_taken=transition_result.transition_taken,
            no_transition_matched=transition_result.no_transition_matched,
            tool_calls_made=tool_calls_made,
            response_chars=response_chars,
        )

        updated_session = await self._update_session_after_response(
            session=session,
            inbound_event=enriched_inbound_event,
            new_state=transition_result.new_state,
            classification=classification,
        )
        self._set_sentry_tags(
            lead_id=lead_profile.id,
            conversation_id=conversation_id,
            fsm_state=updated_session.current_state,
        )
        if classification.intent == "opt_out":
            await self._silenced_user_repository.silence(
                enriched_inbound_event.from_phone,
                reason="opt_out_by_user",
                silenced_by="orchestrator",
            )
            logger.info(
                "orchestrator_opt_out_detected",
                phone=enriched_inbound_event.from_phone,
                message_id=enriched_inbound_event.message_id,
                matched_keyword=classification.metadata.get("matched_keyword"),
            )
        elif classification.intent == "handoff_request":
            logger.info(
                "orchestrator_handoff_requested",
                phone=enriched_inbound_event.from_phone,
                message_id=enriched_inbound_event.message_id,
                matched_keyword=classification.metadata.get("matched_keyword"),
            )
            await self._send_handoff_acknowledgement(
                inbound_event=enriched_inbound_event,
                response_text=str(
                    classification.metadata.get("handoff_response_text")
                    or "Un asesor te contactara pronto."
                ),
            )
            await self._route_handoff_to_branch(
                inbound_event=enriched_inbound_event,
                lead_profile=lead_profile,
                session=updated_session,
                conversation_id=conversation_id,
            )
            updated_session = await self._activate_handoff_session(
                session=updated_session,
                inbound_event=enriched_inbound_event,
            )
        elif classification.intent == "unsupported":
            await self._send_unsupported_message(enriched_inbound_event)
        else:
            conversation_history = await self._build_recent_conversation_history(
                conversation_id=conversation_id,
                limit=10,
            )
            await self._conversation_agent.respond(
                enriched_inbound_event,
                updated_session,
                conversation_history=conversation_history,
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

    async def _get_or_create_lead_profile(
        self, inbound_event: InboundEvent
    ) -> tuple[LeadProfile, bool]:
        existing = await self._lead_profile_repository.get_by_phone(inbound_event.from_phone)
        if existing is not None:
            return existing, False

        now = datetime.now(UTC)
        push_name = inbound_event.raw_metadata.get("push_name")
        lead_name = push_name if isinstance(push_name, str) and push_name else None

        created = await self._lead_profile_repository.upsert_by_phone(
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
        return created, True

    async def _update_lead_profile_from_inbound(
        self,
        lead_profile: LeadProfile,
        inbound_event: InboundEvent,
    ) -> LeadProfile:
        hints = self._extract_lead_hints(inbound_event.text)
        push_name = self._extract_push_name(inbound_event)
        attributes = dict(lead_profile.attributes)
        changed = False
        for key in ("city", "budget", "vehicle_interest"):
            value = hints.get(key)
            if value is None:
                continue
            if attributes.get(key) != value:
                attributes[key] = value
                changed = True

        name = lead_profile.name
        hinted_name = hints.get("name")
        if isinstance(hinted_name, str) and hinted_name:
            if name != hinted_name:
                name = hinted_name
                changed = True
        elif not name and push_name:
            name = push_name
            changed = True

        if not changed:
            return lead_profile

        now = datetime.now(UTC)
        updated = lead_profile.model_copy(
            update={
                "name": name,
                "attributes": attributes,
                "updated_at": now,
            }
        )
        return await self._lead_profile_repository.upsert_by_phone(updated)

    async def _enqueue_lead_upsert(
        self,
        lead_profile: LeadProfile,
        session: Session,
        inbound_event: InboundEvent,
        context_source: str,
    ) -> None:
        payload = self._build_crm_upsert_payload(
            lead_profile=lead_profile,
            session=session,
            inbound_event=inbound_event,
        )
        await self._crm_outbox_repository.enqueue_operation(
            aggregate_id=str(lead_profile.id),
            operation="upsert_lead",
            payload=payload,
        )
        logger.info(
            "crm_upsert_lead_enqueued",
            lead_id=str(lead_profile.id),
            fsm_state=session.current_state,
            context_source=context_source,
            has_vehicle_interest=bool(payload.get("vehicle_interest")),
            has_budget=bool(payload.get("budget")),
            has_city=bool(payload.get("city")),
        )

    @staticmethod
    def _build_crm_upsert_payload(
        lead_profile: LeadProfile,
        session: Session,
        inbound_event: InboundEvent,
    ) -> dict[str, object]:
        attributes = dict(lead_profile.attributes)
        payload: dict[str, object] = {
            "phone": lead_profile.phone,
            "name": lead_profile.name,
            "source": lead_profile.source,
            "fsm_state": session.current_state,
            "last_message_text": inbound_event.text,
        }
        for key in ("city", "budget", "vehicle_interest"):
            value = attributes.get(key)
            if value is not None:
                payload[key] = value
        return payload

    @staticmethod
    def _extract_lead_hints(inbound_text: str | None) -> dict[str, object]:
        text = (inbound_text or "").strip()
        if not text:
            return {}

        hints: dict[str, object] = {}
        normalized_text = text.lower()

        budget_match = re.search(
            r"(?:presupuesto|\\$|mxn|pesos?)\\s*(?::|de)?\\s*([0-9][0-9.,]{2,})",
            normalized_text,
        )
        if budget_match:
            digits = re.sub(r"[^0-9]", "", budget_match.group(1))
            if digits:
                hints["budget"] = int(digits)

        vehicle_keywords = [
            "torton",
            "rabon",
            "tracto",
            "tractocamion",
            "camioneta",
            "volteo",
            "caja seca",
            "remolque",
        ]
        for keyword in vehicle_keywords:
            if keyword in normalized_text:
                hints["vehicle_interest"] = keyword
                break

        comma_parts = [part.strip() for part in text.split(",") if part.strip()]
        if len(comma_parts) >= 2:
            maybe_name = comma_parts[0]
            maybe_city = comma_parts[1]
            if InboundMessageHandler._is_plain_text_name(maybe_name):
                hints["name"] = maybe_name
            if InboundMessageHandler._is_plain_text_name(maybe_city):
                hints["city"] = maybe_city

        return hints

    @staticmethod
    def _is_plain_text_name(value: str) -> bool:
        if not value or len(value) > 60:
            return False
        if re.search(r"[0-9]", value):
            return False
        if re.search(r"[@:/]", value):
            return False
        return True

    async def _get_or_create_session(self, lead_id: UUID, occurred_at: datetime) -> Session:
        existing = await self._session_repository.get_by_lead_id(lead_id)
        if existing is not None:
            return existing

        now = datetime.now(UTC)
        return await self._session_repository.upsert(
            Session(
                id=uuid4(),
                lead_id=lead_id,
                current_state=self._fsm_config.initial_state,
                context={},
                created_at=now,
                updated_at=now,
                last_event_at=occurred_at,
            )
        )

    async def _update_session_after_response(
        self,
        session: Session,
        inbound_event: InboundEvent,
        new_state: str,
        classification: MessageClassification,
    ) -> Session:
        now = datetime.now(UTC)
        new_context = dict(session.context)
        new_context["last_inbound_message"] = {
            "text": inbound_event.text,
            "type": inbound_event.kind.value,
            "timestamp": inbound_event.received_at.isoformat(),
        }
        new_context["last_classification"] = {
            "intent": classification.intent,
            "confidence": classification.confidence,
            "fsm_event": classification.fsm_event,
            "metadata": classification.metadata,
        }

        updated_session = Session(
            id=session.id,
            lead_id=session.lead_id,
            current_state=new_state,
            context=new_context,
            created_at=session.created_at,
            updated_at=now,
            last_event_at=inbound_event.received_at,
        )
        return await self._session_repository.upsert(updated_session)

    def _build_fsm_context(
        self,
        inbound_event: InboundEvent,
        lead_profile: LeadProfile,
        session: Session,
        classification: MessageClassification,
    ) -> dict[str, object]:
        context = dict(session.context)
        context.update(
            {
                "phone": inbound_event.from_phone,
                "name": lead_profile.name,
                "lead_id": str(lead_profile.id),
                "lead_external_crm_id": lead_profile.external_crm_id,
                "session_id": str(session.id),
                "session_context": dict(session.context),
                "lead_attributes": dict(lead_profile.attributes),
                "is_silenced": False,
                "opt_out_detected": classification.intent == "opt_out",
                "campaign_id": session.context.get("campaign_id"),
                "correlation_id": inbound_event.message_id,
                "inbound_text": inbound_event.text,
            }
        )
        return context

    async def _send_handoff_acknowledgement(
        self,
        inbound_event: InboundEvent,
        response_text: str,
    ) -> None:
        correlation_id = inbound_event.message_id
        try:
            await self._messaging_provider.send_text(
                to=inbound_event.from_phone,
                text=response_text,
                correlation_id=correlation_id,
            )
            logger.info(
                "handoff_ack_sent",
                phone=inbound_event.from_phone,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.exception(
                "handoff_ack_send_failed",
                phone=inbound_event.from_phone,
                correlation_id=correlation_id,
            )

    async def _send_unsupported_message(self, inbound_event: InboundEvent) -> None:
        correlation_id = inbound_event.message_id
        text = "Recibi tu mensaje pero no puedo procesar ese tipo de contenido todavia."
        try:
            await self._messaging_provider.send_text(
                to=inbound_event.from_phone,
                text=text,
                correlation_id=correlation_id,
            )
            logger.info(
                "unsupported_message_response_sent",
                phone=inbound_event.from_phone,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.exception(
                "unsupported_message_response_failed",
                phone=inbound_event.from_phone,
                correlation_id=correlation_id,
            )

    def _resolve_session_state(self, session_state: str) -> str:
        if session_state in self._fsm_config.states:
            return session_state

        logger.warning(
            "fsm_unknown_session_state_fallback",
            session_state=session_state,
            fallback_state=self._fsm_config.initial_state,
        )
        return self._fsm_config.initial_state

    async def _enrich_event_for_processing(
        self, inbound_event: InboundEvent
    ) -> tuple[InboundEvent, str | None]:
        if inbound_event.kind is MessageKind.AUDIO:
            return await self._enrich_audio_event(inbound_event)
        if inbound_event.kind is MessageKind.IMAGE:
            return await self._enrich_image_event(inbound_event)
        return inbound_event, None

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

    async def _enrich_audio_event(
        self, inbound_event: InboundEvent
    ) -> tuple[InboundEvent, str | None]:
        media_url = inbound_event.media_url
        metadata = dict(inbound_event.metadata)
        if media_url is None:
            logger.warning("audio_transcription_failed", message_id=inbound_event.message_id)
            return (
                replace(inbound_event, metadata=metadata),
                "Recibi tu nota de voz pero no pude escucharla bien. "
                "Puedes escribirme lo que necesitas?",
            )

        mime_type = self._guess_audio_mime_type(media_url)
        transcription_text = await self._transcription_provider.transcribe(
            audio_url=media_url,
            mime_type=mime_type,
            metadata=metadata,
        )
        if transcription_text is None:
            logger.warning(
                "audio_transcription_failed",
                message_id=inbound_event.message_id,
                media_url=media_url,
                mime_type=mime_type,
            )
            metadata["transcription_failed"] = True
            return (
                replace(inbound_event, metadata=metadata),
                "Recibi tu nota de voz pero no pude escucharla bien. "
                "Puedes escribirme lo que necesitas?",
            )

        logger.info(
            "audio_transcribed",
            message_id=inbound_event.message_id,
            chars=len(transcription_text),
            media_url=media_url,
        )
        metadata["transcription_text"] = transcription_text
        return (
            replace(
                inbound_event,
                text=transcription_text if inbound_event.text is None else inbound_event.text,
                metadata=metadata,
            ),
            None,
        )

    async def _enrich_image_event(
        self, inbound_event: InboundEvent
    ) -> tuple[InboundEvent, str | None]:
        media_url = inbound_event.media_url
        metadata = dict(inbound_event.metadata)
        if media_url is None:
            logger.warning("image_analysis_failed", message_id=inbound_event.message_id)
            return (
                replace(inbound_event, metadata=metadata),
                "Vi que me mandaste una imagen, pero no pude verla bien. "
                "Puedes decirme que me quieres mostrar?",
            )

        description = await self._image_analysis_service.analyze(media_url)
        if description is None:
            logger.warning(
                "image_analysis_failed",
                message_id=inbound_event.message_id,
                media_url=media_url,
            )
            metadata["image_analysis_failed"] = True
            return (
                replace(inbound_event, metadata=metadata),
                "Vi que me mandaste una imagen, pero no pude verla bien. "
                "Puedes decirme que me quieres mostrar?",
            )

        logger.info(
            "image_analyzed",
            message_id=inbound_event.message_id,
            media_url=media_url,
        )
        metadata["image_description"] = description
        image_context = f"[El cliente envio una imagen: {description}]"
        text = f"{inbound_event.text}\n{image_context}" if inbound_event.text else image_context
        return replace(inbound_event, text=text, metadata=metadata), None

    async def _send_media_processing_failure_response(
        self,
        inbound_event: InboundEvent,
        response_text: str,
    ) -> None:
        correlation_id = inbound_event.message_id
        try:
            await self._messaging_provider.send_text(
                to=inbound_event.from_phone,
                text=response_text,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.exception(
                "media_processing_failure_response_failed",
                phone=inbound_event.from_phone,
                correlation_id=correlation_id,
            )

    async def _route_handoff_to_branch(
        self,
        inbound_event: InboundEvent,
        lead_profile: LeadProfile,
        session: Session,
        conversation_id: UUID,
    ) -> None:
        branch = self._resolve_handoff_branch(lead_profile=lead_profile, session=session)
        if branch is None:
            logger.warning(
                "handoff_branch_not_found",
                lead_id=str(lead_profile.id),
                phone=inbound_event.from_phone,
            )
            return

        message = await self._build_handoff_notification(
            inbound_event=inbound_event,
            lead_profile=lead_profile,
            conversation_id=conversation_id,
            branch=branch,
        )
        for phone in branch.phones:
            try:
                await self._messaging_provider.send_text(
                    to=phone,
                    text=message,
                    correlation_id=inbound_event.message_id,
                )
            except Exception:
                logger.exception(
                    "handoff_routing_send_failed",
                    lead_id=str(lead_profile.id),
                    branch_key=branch.sucursal_key,
                    branch_phone=phone,
                )

    async def _build_handoff_notification(
        self,
        inbound_event: InboundEvent,
        lead_profile: LeadProfile,
        conversation_id: UUID,
        branch: Branch,
    ) -> str:
        vehicle_interest = self._extract_handoff_field(
            lead_profile=lead_profile,
            keys=["vehiculo_interes", "vehiculo_previo", "vehicle_interest", "interes_modelo"],
        )
        summary = await self._build_conversation_summary(conversation_id=conversation_id)
        lead_name = (
            lead_profile.name or self._extract_push_name(inbound_event) or "Cliente sin nombre"
        )

        return (
            "[Handoff solicitado]\n"
            f"Sucursal: {branch.display_name} ({branch.sucursal_key})\n"
            f"Nombre cliente: {lead_name}\n"
            f"Telefono cliente: {inbound_event.from_phone}\n"
            f"Vehiculo de interes: {vehicle_interest or 'No especificado'}\n"
            f"Resumen: {summary}"
        )

    async def _build_conversation_summary(self, conversation_id: UUID) -> str:
        events = await self._conversation_event_repository.list_by_conversation(
            conversation_id=conversation_id,
            limit=6,
        )
        fragments: list[str] = []
        for event in events:
            text = event.payload.get("text")
            if isinstance(text, str) and text.strip():
                normalized = " ".join(text.strip().split())
                fragments.append(normalized)

        if not fragments:
            return "Sin contexto adicional."

        return " | ".join(fragments[-3:])

    async def _build_recent_conversation_history(
        self,
        conversation_id: UUID,
        limit: int = 10,
    ) -> list[ConversationEvent]:
        events = await self._conversation_event_repository.list_by_conversation(
            conversation_id=conversation_id,
            limit=50,
        )
        dialogue_events = [
            event for event in events if event.event_type in {"inbound_message", "outbound_message"}
        ]
        return dialogue_events[-limit:]

    async def _activate_handoff_session(
        self,
        session: Session,
        inbound_event: InboundEvent,
    ) -> Session:
        now = datetime.now(UTC)
        context = dict(session.context)
        context["handoff"] = {
            "active": True,
            "activated_at": now.isoformat(),
            "trigger_message_id": inbound_event.message_id,
        }
        return await self._session_repository.upsert(
            Session(
                id=session.id,
                lead_id=session.lead_id,
                current_state="handoff_active",
                context=context,
                created_at=session.created_at,
                updated_at=now,
                last_event_at=inbound_event.received_at,
            )
        )

    def _resolve_handoff_branch(self, lead_profile: LeadProfile, session: Session) -> Branch | None:
        branch_key = self._extract_handoff_field(
            lead_profile=lead_profile,
            session=session,
            keys=["sucursal_key", "branch_key"],
        )
        if branch_key:
            by_key = self._branch_provider.get_branch_by_key(branch_key)
            if by_key is not None:
                return by_key

        centro = self._extract_handoff_field(
            lead_profile=lead_profile,
            session=session,
            keys=["centro_sheet", "centro", "centro_inventario"],
        )
        if centro:
            by_centro = self._branch_provider.get_branch_by_centro(centro)
            if by_centro is not None:
                return by_centro

        city = self._extract_handoff_field(
            lead_profile=lead_profile,
            session=session,
            keys=["city", "ciudad"],
        )
        if city:
            by_city = self._find_branch_by_city(city)
            if by_city is not None:
                return by_city

        branches = self._branch_provider.list_branches()
        fallback = next(
            (item for item in branches if item.sucursal_key.strip().casefold() == "fallback"),
            None,
        )
        if fallback is not None:
            return fallback
        if branches:
            return branches[0]
        return None

    def _find_branch_by_city(self, city: str) -> Branch | None:
        normalized_city = city.strip().casefold()
        if not normalized_city:
            return None

        for branch in self._branch_provider.list_branches():
            centro = branch.centro_sheet.strip().casefold()
            display_name = branch.display_name.strip().casefold()
            if normalized_city == centro or normalized_city in display_name:
                return branch
        return None

    def _extract_handoff_field(
        self,
        lead_profile: LeadProfile,
        keys: list[str],
        session: Session | None = None,
    ) -> str | None:
        candidates: list[dict[str, object]] = [lead_profile.attributes]
        if session is not None:
            candidates.append(session.context)
            last_inbound = session.context.get("last_inbound_message")
            if isinstance(last_inbound, dict):
                candidates.append(last_inbound)

        for payload in candidates:
            for key in keys:
                value = payload.get(key)
                if isinstance(value, str):
                    cleaned = value.strip()
                    if cleaned:
                        return cleaned
        return None

    @staticmethod
    def _extract_push_name(inbound_event: InboundEvent) -> str | None:
        push_name = inbound_event.raw_metadata.get("push_name")
        if not isinstance(push_name, str):
            return None
        normalized = push_name.strip()
        if not normalized:
            return None
        return normalized

    async def _should_defer_due_newer_inbound(
        self,
        conversation_id: UUID,
        current_message_id: str,
    ) -> bool:
        if self._message_accumulation_seconds <= 0:
            return False

        await asyncio.sleep(self._message_accumulation_seconds)
        events = await self._conversation_event_repository.list_by_conversation(
            conversation_id=conversation_id,
            limit=20,
        )
        latest_inbound = self._find_latest_inbound_message_id(events)
        return latest_inbound is not None and latest_inbound != current_message_id

    @staticmethod
    def _find_latest_inbound_message_id(events: list[ConversationEvent]) -> str | None:
        for event in reversed(events):
            if event.event_type != "inbound_message":
                continue
            if event.message_id:
                return event.message_id
            message_id = event.payload.get("message_id")
            if isinstance(message_id, str) and message_id.strip():
                return message_id.strip()
        return None

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

    @staticmethod
    def _set_sentry_tags(lead_id: UUID, conversation_id: UUID, fsm_state: str) -> None:
        scope = sentry_sdk.get_current_scope()
        scope.set_tag("lead_id", str(lead_id))
        scope.set_tag("conversation_id", str(conversation_id))
        scope.set_tag("fsm_state", fsm_state)
