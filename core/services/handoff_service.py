from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from core.brand.schema import BrandConfig
from core.domain.conversation_event import ConversationEvent
from core.domain.session import Session
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import ConversationEventRepository, SessionRepository

logger = structlog.get_logger("super_agent_platform.core.services.handoff_service")


def _build_advisor_alert(
    lead_name: str | None,
    phone: str,
    vehicle_interest: str | None,
    city: str | None,
    budget: float | None,
) -> str:
    """
    Build enriched handoff alert text for advisor.
    Pure function with no IO.
    """
    name = lead_name or "Prospecto"

    if budget or city:
        urgency = "🔴 Alta"
    elif vehicle_interest:
        urgency = "🟡 Media"
    else:
        urgency = "🟢 Normal"

    import re

    digits = re.sub(r"\D", "", phone)
    wa_link = f"https://wa.me/{digits}"
    vehicle = vehicle_interest or "No especificado"

    lines = [
        "🚛 Nuevo lead listo para atención",
        "",
        f"👤 Nombre: {name}",
        f"🚚 Interés: {vehicle}",
    ]
    if city:
        lines.append(f"📍 Ciudad: {city}")
    if budget:
        lines.append(f"💰 Presupuesto: ${budget:,.0f}")
    lines += [
        f"⚡ Urgencia: {urgency}",
        f"📞 WhatsApp: {wa_link}",
        "",
        "💬 Acción: Responde directamente desde este número —",
        "el bot se silenciará automáticamente al detectar tu mensaje.",
    ]
    return "\n".join(lines)


def _urgency_level(
    vehicle_interest: str | None,
    city: str | None,
    budget: float | None,
) -> str:
    if budget or city:
        return "Alta"
    if vehicle_interest:
        return "Media"
    return "Normal"


def _maybe_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _first_non_empty(*values: object) -> str:
    for value in values:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return ""


def _classify_handoff_state(
    session_context: dict[str, object],
) -> str:
    """
    Classify post-handoff state for observability.
    Returns one of: responded, interested, active, stop, error, pending.
    """
    if session_context.get("advisor_responded"):
        return "responded"
    if session_context.get("opt_out") or session_context.get("is_silenced"):
        return "stop"

    vehicle = session_context.get("vehicle_interest") or session_context.get("vehiculo_interes")
    if isinstance(vehicle, str) and vehicle.strip():
        return "interested"

    fsm_state = str(session_context.get("current_state", ""))
    if fsm_state == "handoff_active":
        return "active"
    if fsm_state == "handoff_pending":
        return "pending"
    return "pending"


class HandoffService:
    def __init__(
        self,
        session_repository: SessionRepository,
        conversation_event_repository: ConversationEventRepository,
        messaging_provider: MessagingProvider | None = None,
        brand_config: BrandConfig | None = None,
    ) -> None:
        self._session_repository = session_repository
        self._conversation_event_repository = conversation_event_repository
        self._messaging = messaging_provider
        self._brand_config = brand_config

    async def take_control(self, lead_id: UUID) -> Session:
        session = await self._get_session_by_lead_id(lead_id)
        correlation_id = str(session.id)
        try:
            logger.info(
                "handoff_started",
                lead_id=str(session.lead_id),
                correlation_id=correlation_id,
                evento="handoff_started",
                resultado="ok",
                branch=None,
            )
            await self._session_repository.update_state(
                session_id=session.id,
                new_state="handoff_active",
                context=dict(session.context),
            )
            updated_session = await self._get_session_by_lead_id(lead_id)
            await self._send_handoff_alert(updated_session)
            await self._append_system_event(updated_session, "system_agent_took_control")
            logger.info(
                "handoff_ok",
                lead_id=str(updated_session.lead_id),
                correlation_id=correlation_id,
                evento="handoff_ok",
                resultado="ok",
                branch=None,
            )
            logger.info(
                "handoff_take_control_applied",
                lead_id=str(updated_session.lead_id),
                session_id=str(updated_session.id),
                state=updated_session.current_state,
            )
            return updated_session
        except Exception:
            logger.error(
                "handoff_error",
                lead_id=str(session.lead_id),
                correlation_id=correlation_id,
                evento="handoff_error",
                resultado="error",
                branch=None,
                exc_info=True,
            )
            raise

    async def release_control(self, lead_id: UUID) -> Session:
        session = await self._get_session_by_lead_id(lead_id)
        correlation_id = str(session.id)
        try:
            logger.info(
                "handoff_started",
                lead_id=str(session.lead_id),
                correlation_id=correlation_id,
                evento="handoff_started",
                resultado="ok",
                branch=None,
            )
            await self._session_repository.update_state(
                session_id=session.id,
                new_state="idle",
                context=dict(session.context),
            )
            updated_session = await self._get_session_by_lead_id(lead_id)
            await self._append_system_event(updated_session, "system_agent_released_control")
            logger.info(
                "handoff_ok",
                lead_id=str(updated_session.lead_id),
                correlation_id=correlation_id,
                evento="handoff_ok",
                resultado="ok",
                branch=None,
            )
            logger.info(
                "handoff_release_control_applied",
                lead_id=str(updated_session.lead_id),
                session_id=str(updated_session.id),
                state=updated_session.current_state,
            )
            return updated_session
        except Exception:
            logger.error(
                "handoff_error",
                lead_id=str(session.lead_id),
                correlation_id=correlation_id,
                evento="handoff_error",
                resultado="error",
                branch=None,
                exc_info=True,
            )
            raise

    async def _get_session_by_lead_id(self, lead_id: UUID) -> Session:
        session = await self._session_repository.get_by_lead_id(lead_id)
        if session is None:
            raise ValueError(f"session not found for lead_id={lead_id}")
        return session

    async def _append_system_event(self, session: Session, event_type: str) -> None:
        now = datetime.now(UTC)
        await self._conversation_event_repository.append(
            ConversationEvent(
                id=uuid4(),
                conversation_id=session.id,
                lead_id=session.lead_id,
                event_type=event_type,
                payload={
                    "lead_id": str(session.lead_id),
                    "session_id": str(session.id),
                    "state": session.current_state,
                },
                created_at=now,
                message_id=None,
            )
        )

    async def _send_handoff_alert(self, session: Session) -> None:
        """
        Build and send enriched handoff alert to advisor.
        Best effort: never raises.
        """
        try:
            context = session.context
            lead_attributes = context.get("lead_attributes")
            attrs = lead_attributes if isinstance(lead_attributes, dict) else {}

            lead_name = context.get("name")
            if not isinstance(lead_name, str):
                lead_name = attrs.get("name") if isinstance(attrs.get("name"), str) else None

            phone = _first_non_empty(context.get("phone"), attrs.get("phone"))
            vehicle_interest = (
                attrs.get("vehicle_interest")
                if isinstance(attrs.get("vehicle_interest"), str)
                else (
                    attrs.get("vehiculo_interes")
                    if isinstance(attrs.get("vehiculo_interes"), str)
                    else None
                )
            )
            city = (
                attrs.get("city")
                if isinstance(attrs.get("city"), str)
                else attrs.get("ciudad") if isinstance(attrs.get("ciudad"), str) else None
            )
            budget = _maybe_float(attrs.get("budget"))

            alert_text = _build_advisor_alert(
                lead_name=lead_name,
                phone=phone,
                vehicle_interest=vehicle_interest,
                city=city,
                budget=budget,
            )

            state_context = dict(context)
            state_context.setdefault("current_state", session.current_state)
            handoff_state = _classify_handoff_state(state_context)
            logger.info(
                "handoff_state_classified",
                state=handoff_state,
                lead_id=str(session.lead_id),
            )

            logger.info(
                "handoff_alert_enriched",
                lead_id=str(session.lead_id),
                urgency=_urgency_level(vehicle_interest, city, budget),
                has_vehicle=bool(vehicle_interest),
                has_city=bool(city),
                has_budget=bool(budget),
                message=alert_text,
            )

            configured_phone = (
                self._brand_config.handoff.notification_phone if self._brand_config else ""
            )
            advisor_phone = _first_non_empty(
                context.get("branch_phone"),
                context.get("sucursal_phone"),
                configured_phone,
            )

            if not advisor_phone:
                logger.warning(
                    "handoff_alert_no_phone",
                    reason="notification_phone not configured",
                )
                return

            if self._messaging is None:
                logger.warning(
                    "handoff_alert_no_messaging",
                    reason="MessagingProvider not injected",
                )
                return

            try:
                await self._messaging.send_text(
                    to=advisor_phone,
                    text=alert_text,
                    correlation_id=str(session.lead_id),
                )
                logger.info(
                    "handoff_alert_sent",
                    advisor_phone=advisor_phone[:4] + "***",
                    lead_id=str(session.lead_id),
                )
            except Exception as exc:
                logger.warning(
                    "handoff_alert_send_failed",
                    reason=str(exc),
                    lead_id=str(session.lead_id),
                )
        except Exception as exc:
            logger.warning(
                "handoff_alert_build_failed",
                reason=str(exc),
                lead_id=str(session.lead_id),
            )
