from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from core.domain.conversation_event import ConversationEvent
from core.domain.session import Session
from core.ports.repositories import ConversationEventRepository, SessionRepository

logger = structlog.get_logger("super_agent_platform.core.services.handoff_service")


class HandoffService:
    def __init__(
        self,
        session_repository: SessionRepository,
        conversation_event_repository: ConversationEventRepository,
    ) -> None:
        self._session_repository = session_repository
        self._conversation_event_repository = conversation_event_repository

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
