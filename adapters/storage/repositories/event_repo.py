from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
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

    async def list_by_lead_id(self, lead_id: UUID, limit: int = 1000) -> list[ConversationEvent]:
        async with session_scope() as session:
            statement = (
                select(ConversationEventModel)
                .where(ConversationEventModel.lead_id == lead_id)
                .order_by(ConversationEventModel.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(statement)
            models = result.scalars().all()

        return [_to_domain(model) for model in models]

    async def count_since(self, since: datetime) -> int:
        async with session_scope() as session:
            statement = (
                select(func.count())
                .select_from(ConversationEventModel)
                .where(ConversationEventModel.created_at >= since)
            )
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_by_type_since(self, event_type: str, since: datetime) -> int:
        async with session_scope() as session:
            statement = (
                select(func.count())
                .select_from(ConversationEventModel)
                .where(
                    ConversationEventModel.event_type == event_type,
                    ConversationEventModel.created_at >= since,
                )
            )
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def average_response_time_minutes_since(self, since: datetime) -> float | None:
        async with session_scope() as session:
            inbound_subquery = (
                select(
                    ConversationEventModel.conversation_id.label("conversation_id"),
                    func.min(ConversationEventModel.created_at).label("first_inbound_at"),
                )
                .where(
                    ConversationEventModel.event_type == "inbound_message",
                    ConversationEventModel.created_at >= since,
                )
                .group_by(ConversationEventModel.conversation_id)
                .subquery()
            )

            outbound_subquery = (
                select(
                    ConversationEventModel.conversation_id.label("conversation_id"),
                    func.min(ConversationEventModel.created_at).label("first_outbound_at"),
                )
                .where(ConversationEventModel.event_type == "outbound_message")
                .group_by(ConversationEventModel.conversation_id)
                .subquery()
            )

            statement = (
                select(
                    func.avg(
                        func.extract(
                            "epoch",
                            outbound_subquery.c.first_outbound_at - inbound_subquery.c.first_inbound_at,
                        )
                        / 60.0
                    )
                )
                .select_from(inbound_subquery)
                .join(
                    outbound_subquery,
                    outbound_subquery.c.conversation_id == inbound_subquery.c.conversation_id,
                )
                .where(outbound_subquery.c.first_outbound_at >= inbound_subquery.c.first_inbound_at)
            )

            result = await session.execute(statement)
            value = result.scalar_one_or_none()
            if value is None:
                return None
            return float(value)

    @staticmethod
    def _is_dedup_violation(error: IntegrityError) -> bool:
        error_text = str(error.orig)
        return _DEDUP_INDEX_NAME in error_text or "duplicate key value" in error_text
