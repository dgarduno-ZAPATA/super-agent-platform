from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TypeVar
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sentry_sdk
import structlog

from core.brand.schema import Brand
from core.domain.conversation_event import ConversationEvent
from core.domain.llm import LLMResponse, ToolResult
from core.domain.messaging import ChatMessage, InboundEvent
from core.domain.session import Session
from core.fsm.tool_policy import get_allowed_tools
from core.ports.llm_provider import LLMProvider
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import ConversationEventRepository
from core.services.friction_detector import detect_friction
from core.services.repetition_guard import is_repetition
from core.services.skills import SkillExecutionContext, SkillRegistry

logger = structlog.get_logger("super_agent_platform.core.services.conversation_agent")
_ToolSchemaT = TypeVar("_ToolSchemaT")
MAX_REGEN_ATTEMPTS = 2
HANDOFF_STATES = {"handoff_pending", "handoff_active"}


def _tool_schema_name(schema: object) -> str | None:
    if isinstance(schema, dict):
        function = schema.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str):
                return name
    name = getattr(schema, "name", None)
    if isinstance(name, str):
        return name
    return None


def _filter_tool_schemas(
    all_schemas: list[_ToolSchemaT],
    allowed_tools: list[str] | None,
) -> list[_ToolSchemaT]:
    if allowed_tools is None:
        return all_schemas
    allowed = set(allowed_tools)
    return [schema for schema in all_schemas if _tool_schema_name(schema) in allowed]


def should_send_handoff_message(
    current_state: str,
    recent_bot_messages: list[str],
    handoff_msg: str,
) -> bool:
    """
    True si debe enviarse el mensaje neutro de espera.
    False si debe haber silencio (ya se envió).
    """
    if current_state not in HANDOFF_STATES:
        return False
    already_sent = any(handoff_msg in msg for msg in recent_bot_messages[-2:])
    return not already_sent


class ConversationAgent:
    def __init__(
        self,
        llm_provider: LLMProvider,
        messaging_provider: MessagingProvider,
        brand: Brand,
        conversation_event_repository: ConversationEventRepository,
        skill_registry: SkillRegistry,
    ) -> None:
        self._llm_provider = llm_provider
        self._messaging_provider = messaging_provider
        self._brand = brand
        self._conversation_event_repository = conversation_event_repository
        self._skill_registry = skill_registry

    async def respond(
        self,
        event: InboundEvent,
        session: Session,
        conversation_history: list[ConversationEvent] | None = None,
    ) -> None:
        correlation_id = self._extract_correlation_id(event)
        conversation_id = self._build_conversation_id(event.from_phone)

        try:
            history = conversation_history
            if history is None:
                history = await self._conversation_event_repository.list_by_conversation(
                    conversation_id=conversation_id,
                    limit=30,
                )

            messages = self._format_history_as_messages(history)
            messages = self._ensure_current_user_message(messages=messages, event=event)
            if not messages:
                messages = [self._build_user_message(event)]
            messages = self._trim_messages_for_budget(messages, max_total_chars=4000)
            handoff_msg = self._brand.brand.system_messages.handoff_waiting
            friction_msg = self._brand.brand.system_messages.friction_escalation

            if session.current_state in HANDOFF_STATES:
                recent_bot_messages = [
                    msg.content
                    for msg in messages
                    if msg.role == "assistant" and isinstance(msg.content, str) and msg.content
                ]
                if should_send_handoff_message(
                    session.current_state,
                    recent_bot_messages,
                    handoff_msg,
                ):
                    delivery = await self._messaging_provider.send_text(
                        to=event.from_phone,
                        text=handoff_msg,
                        correlation_id=correlation_id,
                    )
                    await self._persist_outbound_event(
                        conversation_id=conversation_id,
                        lead_id=session.lead_id,
                        text=handoff_msg,
                        correlation_id=correlation_id,
                        provider_message_id=delivery.message_id,
                        state=session.current_state,
                        llm_metadata={"source": "handoff_wait_message"},
                    )
                    logger.info(
                        "conversation_agent_handoff_wait_sent",
                        conversation_id=str(conversation_id),
                        lead_id=str(session.lead_id),
                        state=session.current_state,
                        correlation_id=correlation_id,
                    )
                return

            if self._is_photo_only_request(event.text):
                await self._handle_photo_only_request(
                    event=event,
                    session=session,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                )
                return

            system_prompt = self._build_system_prompt(session.current_state)
            if session.current_state == "catalog_navigation":
                inventory_context = self._build_catalog_inventory_prompt_context(event.text)
                system_prompt = f"{system_prompt}\n\n{inventory_context}"
            allowed = get_allowed_tools(session.current_state)
            previous_bot_texts = [
                msg.content
                for msg in messages
                if msg.role == "assistant" and isinstance(msg.content, str) and msg.content
            ]
            attempt = 0
            while True:
                llm_response = await self._run_tool_calling_loop(
                    messages=messages[-12:],
                    system_prompt=system_prompt,
                    context=SkillExecutionContext(
                        phone=event.from_phone,
                        correlation_id=correlation_id,
                    ),
                    allowed_tools=allowed,
                )
                response_text = self._compress_response_text(
                    llm_response.content,
                    inbound_text=event.text,
                    history=history,
                )
                if not is_repetition(response_text, previous_bot_texts):
                    break
                attempt += 1
                if attempt <= MAX_REGEN_ATTEMPTS:
                    logger.info(
                        "repetition_regenerating",
                        attempt=attempt,
                        lead_id=str(session.lead_id),
                    )
                    continue
                logger.warning(
                    "repetition_max_attempts_reached",
                    lead_id=str(session.lead_id),
                )
                break
            current_client_message = (event.text or "").strip()
            recent_client_messages = [
                msg.content
                for msg in messages
                if msg.role == "user" and isinstance(msg.content, str) and msg.content
            ]
            if (
                current_client_message
                and recent_client_messages
                and recent_client_messages[-1] == current_client_message
            ):
                recent_client_messages = recent_client_messages[:-1]

            recent_states = [
                state
                for item in history
                if isinstance((state := item.payload.get("state")), str) and state.strip()
            ]
            if not recent_states:
                observed_turns = len(recent_client_messages) + (1 if current_client_message else 0)
                recent_states = [session.current_state] * observed_turns

            outbound_llm_metadata = dict(llm_response.metadata)
            if detect_friction(
                current_client_message=current_client_message,
                recent_client_messages=recent_client_messages,
                current_state=session.current_state,
                recent_states=recent_states,
            ):
                response_text = friction_msg
                outbound_llm_metadata["friction_escalation"] = True
                outbound_llm_metadata["handoff_triggered"] = False
                logger.warning(
                    "friction_escalation_triggered",
                    lead_id=str(session.lead_id),
                    current_state=session.current_state,
                    handoff_triggered=False,
                    reason=(
                        "conversation_agent_no_handoff_dependency;"
                        "handoff must be triggered upstream"
                    ),
                )

            delivery = await self._messaging_provider.send_text(
                to=event.from_phone,
                text=response_text,
                correlation_id=correlation_id,
            )
            await self._persist_outbound_event(
                conversation_id=conversation_id,
                lead_id=session.lead_id,
                text=response_text,
                correlation_id=correlation_id,
                provider_message_id=delivery.message_id,
                state=session.current_state,
                llm_metadata=outbound_llm_metadata,
            )
            logger.info(
                "conversation_agent_response_sent",
                conversation_id=str(conversation_id),
                lead_id=str(session.lead_id),
                state=session.current_state,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.exception(
                "conversation_agent_response_failed",
                conversation_id=str(conversation_id),
                lead_id=str(session.lead_id),
                state=session.current_state,
                correlation_id=correlation_id,
            )
            fallback_text = self._resolve_llm_failure_message()
            try:
                delivery = await self._messaging_provider.send_text(
                    to=event.from_phone,
                    text=fallback_text,
                    correlation_id=correlation_id,
                )
                await self._persist_outbound_event(
                    conversation_id=conversation_id,
                    lead_id=session.lead_id,
                    text=fallback_text,
                    correlation_id=correlation_id,
                    provider_message_id=delivery.message_id,
                    state=session.current_state,
                    llm_metadata={"fallback_type": "both_llms_failed"},
                )
                logger.info(
                    "conversation_agent_failure_fallback_sent",
                    conversation_id=str(conversation_id),
                    lead_id=str(session.lead_id),
                    state=session.current_state,
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.exception(
                    "conversation_agent_failure_fallback_send_failed",
                    conversation_id=str(conversation_id),
                    lead_id=str(session.lead_id),
                    state=session.current_state,
                    correlation_id=correlation_id,
                )

    def _build_system_prompt(self, current_state: str) -> str:
        return (
            f"{self._brand.prompt}\n\n"
            f"ESTADO ACTUAL: {current_state}. "
            "Sigue estrictamente el objetivo de este estado segun tus instrucciones.\n"
            "Estilo obligatorio de respuesta: maximo 3 a 4 oraciones cortas, directas y "
            "conversacionales. No repitas especificaciones tecnicas que ya compartiste en "
            "mensajes previos; si ya las mencionaste, da solo un resumen breve y el siguiente paso."
        )

    def _build_catalog_inventory_prompt_context(self, user_text: str | None) -> str:
        product_hint = (user_text or "").strip() or None
        inventory_snapshot = self._skill_registry.query_inventory(
            product_name=product_hint,
            max_results=3,
        )
        logger.info(
            "catalog_inventory_prompt_context_built",
            query=product_hint,
            has_results=not inventory_snapshot.startswith("No hay productos disponibles"),
        )
        return (
            "CONTEXTO DE INVENTARIO REAL (OBLIGATORIO):\n"
            f"{inventory_snapshot}\n\n"
            "Regla estricta: solo puedes mencionar unidades que aparezcan en ese bloque. "
            "Si no hay resultados, responde que no hay disponibilidad en este momento y "
            "ofrece validar con el equipo humano. "
            "Si el cliente pide fotos o imagenes de una unidad, usa la herramienta "
            "send_inventory_photos con el nombre o SKU de esa unidad. "
            "Nunca digas que no puedes mandar fotos: si hay URLs en inventario, debes enviarlas."
        )

    def _trim_messages_for_budget(
        self, messages: list[ChatMessage], max_total_chars: int
    ) -> list[ChatMessage]:
        if max_total_chars <= 0:
            return messages[-1:] if messages else []

        trimmed: list[ChatMessage] = []
        total = 0
        for message in reversed(messages):
            content_len = len(message.content)
            if trimmed and total + content_len > max_total_chars:
                break
            trimmed.append(message)
            total += content_len
        trimmed.reverse()
        if len(trimmed) != len(messages):
            logger.info(
                "conversation_messages_trimmed_for_budget",
                original_count=len(messages),
                trimmed_count=len(trimmed),
                max_total_chars=max_total_chars,
            )
        return trimmed

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

    @staticmethod
    def _ensure_current_user_message(
        messages: list[ChatMessage], event: InboundEvent
    ) -> list[ChatMessage]:
        current = ConversationAgent._build_user_message(event)
        if not current.content:
            return messages

        if not messages:
            return [current]

        last = messages[-1]
        if last.role == "user" and last.content == current.content:
            return messages

        return [*messages, current]

    def _resolve_llm_failure_message(self) -> str:
        configured = self._brand.fallback_messages.both_llms_failed
        if configured:
            return configured[0]
        return "Disculpa, tengo un problema tecnico. Te escribo en breve."

    def _compress_response_text(
        self,
        text: str,
        inbound_text: str | None,
        history: list[ConversationEvent] | None,
        max_sentences: int = 3,
        max_chars: int = 700,
    ) -> str:
        normalized = " ".join((text or "").strip().split())
        if not normalized:
            return normalized

        if self._is_photo_only_request(inbound_text):
            max_sentences = 1
            max_chars = 220
        elif self._is_photo_request(inbound_text):
            max_sentences = min(max_sentences, 2)
            max_chars = min(max_chars, 320)

        sentence_candidates = re.split(r"(?<=[.!?])\s+", normalized)
        selected: list[str] = []
        seen_keys: set[str] = set()
        history_has_specs = self._history_has_technical_specs(history)
        for sentence in sentence_candidates:
            cleaned = sentence.strip()
            if not cleaned:
                continue
            if history_has_specs and self._looks_like_spec_sentence(cleaned):
                continue
            dedup_key = re.sub(r"\W+", "", cleaned.casefold())
            if dedup_key and dedup_key in seen_keys:
                continue
            if dedup_key:
                seen_keys.add(dedup_key)
            selected.append(cleaned)
            if len(selected) >= max_sentences:
                break

        result = " ".join(selected) if selected else normalized
        if len(result) <= max_chars:
            return result

        clipped = result[:max_chars].rsplit(" ", maxsplit=1)[0].strip()
        if clipped and clipped[-1] not in ".!?":
            clipped = f"{clipped}."
        return clipped or result[:max_chars]

    async def _handle_photo_only_request(
        self,
        event: InboundEvent,
        session: Session,
        conversation_id: UUID,
        correlation_id: str,
    ) -> None:
        photos_result = await self._skill_registry.send_inventory_photos(
            product_name=(event.text or "").strip(),
            context=SkillExecutionContext(
                phone=event.from_phone,
                correlation_id=correlation_id,
            ),
        )
        short_response = self._build_photo_ack_text(photos_result)
        delivery = await self._messaging_provider.send_text(
            to=event.from_phone,
            text=short_response,
            correlation_id=correlation_id,
        )
        await self._persist_outbound_event(
            conversation_id=conversation_id,
            lead_id=session.lead_id,
            text=short_response,
            correlation_id=correlation_id,
            provider_message_id=delivery.message_id,
            state=session.current_state,
            llm_metadata={
                "response_mode": "photo_only_direct",
                "photos_result": photos_result,
            },
        )

    @staticmethod
    def _build_photo_ack_text(photos_result: str) -> str:
        normalized = photos_result.strip()
        if normalized.lower().startswith("listo, te envie"):
            return "Listo, ya te mande las fotos."
        return normalized

    @staticmethod
    def _is_photo_request(text: str | None) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        return "foto" in normalized or "imagen" in normalized

    @staticmethod
    def _is_photo_only_request(text: str | None) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        tokens = re.findall(r"[a-z0-9áéíóúñ]+", normalized, flags=re.IGNORECASE)
        if not tokens:
            return False
        photo_tokens = {"foto", "fotos", "imagen", "imagenes", "imágenes"}
        if not any(token in photo_tokens for token in tokens):
            return False
        return len(tokens) <= 5

    @staticmethod
    def _history_has_technical_specs(history: list[ConversationEvent] | None) -> bool:
        if not history:
            return False
        for item in history:
            if item.event_type != "outbound_message":
                continue
            payload_text = item.payload.get("text")
            if not isinstance(payload_text, str):
                continue
            lowered = payload_text.casefold()
            if "motor:" in lowered or "trans:" in lowered or "km:" in lowered:
                return True
        return False

    @staticmethod
    def _looks_like_spec_sentence(text: str) -> bool:
        lowered = text.casefold()
        keyword_hits = sum(
            1
            for token in ("motor", "transmision", "transmisión", "km", "kilomet")
            if token in lowered
        )
        return keyword_hits >= 2

    async def _run_tool_calling_loop(
        self,
        messages: list[ChatMessage],
        system_prompt: str,
        context: SkillExecutionContext,
        allowed_tools: list[str] | None = None,
    ) -> LLMResponse:
        working_messages = list(messages)
        max_rounds = 3
        for _ in range(max_rounds):
            all_schemas = self._skill_registry.get_tool_schemas()
            schemas_to_use = _filter_tool_schemas(
                all_schemas=all_schemas,
                allowed_tools=allowed_tools,
            )
            if allowed_tools is not None:
                logger.debug(
                    "tool_calling_filtered",
                    allowed=allowed_tools,
                    available=[_tool_schema_name(schema) for schema in schemas_to_use],
                )
            llm_response = await self._llm_provider.complete(
                messages=working_messages,
                system=system_prompt,
                tools=schemas_to_use,
                temperature=0.2,
            )
            if not llm_response.tool_calls:
                return llm_response

            working_messages.append(
                ChatMessage(
                    role="assistant",
                    content=llm_response.content,
                    metadata={"tool_calls": llm_response.tool_calls},
                )
            )

            tool_results: list[ToolResult] = []
            for call in llm_response.tool_calls:
                result = await self._skill_registry.execute_tool(call=call, context=context)
                tool_results.append(result)

            for result in tool_results:
                working_messages.append(
                    ChatMessage(
                        role="tool",
                        name=result.name,
                        tool_call_id=result.tool_call_id,
                        content=result.content,
                        metadata={"is_error": result.is_error, **result.metadata},
                    )
                )

        return llm_response
