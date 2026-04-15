from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from adapters.storage.db import session_scope
from adapters.storage.models import ConversationEventModel
from core.domain.conversation_event import ConversationEvent
from core.ports.repositories import ConversationEventRepository

_DEDUP_INDEX_NAME = "uq_conversation_events_inbound_message_id"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _to_domain(model: ConversationEventModel) -> ConversationEvent:
    payload = dict(model.payload)
    message_id = payload.get("message_id")

    return ConversationEvent(
        id=model.id,
        conversation_id=model.conversation_id,
        lead_id=model.lead_id,
        event_type=model.event_type,
        payload=payload,
        created_at=_ensure_utc(model.created_at),
        message_id=message_id if isinstance(message_id, str) else None,
    )


class PostgresConversationEventRepository(ConversationEventRepository):
    async def append(self, event: ConversationEvent) -> bool:
        payload = dict(event.payload)
        if event.message_id is not None:
            payload["message_id"] = event.message_id

        try:
            async with session_scope() as session:
                session.add(
                    ConversationEventModel(
                        id=event.id,
                        conversation_id=event.conversation_id,
                        lead_id=event.lead_id,
                        event_type=event.event_type,
                        payload=payload,
                        created_at=event.created_at,
                    )
                )
        except IntegrityError as exc:
            if event.event_type == "inbound_message" and self._is_dedup_violation(exc):
                return False
            raise

        return True

    async def list_by_conversation(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[ConversationEvent]:
        async with session_scope() as session:
            statement = (
                select(ConversationEventModel)
                .where(ConversationEventModel.conversation_id == conversation_id)
                .order_by(ConversationEventModel.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(statement)
            models = result.scalars().all()

        return [_to_domain(model) for model in models]

    @staticmethod
    def _is_dedup_violation(error: IntegrityError) -> bool:
        error_text = str(error.orig)
        return _DEDUP_INDEX_NAME in error_text or "duplicate key value" in error_text
