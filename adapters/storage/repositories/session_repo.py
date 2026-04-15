from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import SessionModel
from core.domain.session import Session
from core.ports.repositories import SessionRepository


def _to_domain(model: SessionModel) -> Session:
    return Session(
        id=model.id,
        lead_id=model.lead_id,
        current_state=model.current_state,
        context=model.context_json,
        created_at=_ensure_utc_required(model.created_at),
        updated_at=_ensure_utc_required(model.updated_at),
        last_event_at=_ensure_utc(model.last_event_at),
    )


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _ensure_utc_required(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class PostgresSessionRepository(SessionRepository):
    async def get_by_lead_id(self, lead_id: UUID) -> Session | None:
        async with session_scope() as session:
            statement = select(SessionModel).where(SessionModel.lead_id == lead_id)
            result = await session.execute(statement)
            model = result.scalar_one_or_none()

        return None if model is None else _to_domain(model)

    async def upsert(self, session_entity: Session) -> Session:
        async with session_scope() as session:
            statement = (
                insert(SessionModel)
                .values(
                    id=session_entity.id,
                    lead_id=session_entity.lead_id,
                    current_state=session_entity.current_state,
                    context=session_entity.context,
                    created_at=session_entity.created_at,
                    updated_at=session_entity.updated_at,
                    last_event_at=session_entity.last_event_at,
                )
                .on_conflict_do_update(
                    index_elements=[SessionModel.id],
                    set_={
                        "lead_id": session_entity.lead_id,
                        "current_state": session_entity.current_state,
                        "context": session_entity.context,
                        "updated_at": session_entity.updated_at,
                        "last_event_at": session_entity.last_event_at,
                    },
                )
                .returning(SessionModel)
            )
            result = await session.execute(statement)
            model = result.scalar_one()

        return _to_domain(model)

    async def update_state(
        self, session_id: UUID, new_state: str, context: dict[str, object]
    ) -> None:
        async with session_scope() as session:
            statement = select(SessionModel).where(SessionModel.id == session_id)
            result = await session.execute(statement)
            model = result.scalar_one()
            model.current_state = new_state
            model.context_json = context
            model.updated_at = datetime.now(UTC)
