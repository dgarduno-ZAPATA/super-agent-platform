from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.sql import and_, or_
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

    async def count_not_in_states(self, states: set[str]) -> int:
        async with session_scope() as session:
            statement = select(func.count()).select_from(SessionModel)
            if states:
                statement = statement.where(~SessionModel.current_state.in_(states))
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_by_state(self, state: str) -> int:
        async with session_scope() as session:
            statement = (
                select(func.count())
                .select_from(SessionModel)
                .where(SessionModel.current_state == state)
            )
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_active_since(
        self, since: datetime, excluded_states: set[str] | None = None
    ) -> int:
        async with session_scope() as session:
            statement = select(func.count()).select_from(SessionModel).where(
                or_(
                    SessionModel.last_event_at >= since,
                    and_(SessionModel.last_event_at.is_(None), SessionModel.updated_at >= since),
                )
            )
            if excluded_states:
                statement = statement.where(~SessionModel.current_state.in_(excluded_states))
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_human_control_sessions(self) -> int:
        async with session_scope() as session:
            statement = select(func.count()).select_from(SessionModel).where(
                or_(
                    SessionModel.current_state == "handoff_active",
                    SessionModel.context_json.op("->>")("human_in_control") == "true",
                    SessionModel.context_json.op("->>")("owner") == "human_agent",
                    SessionModel.context_json.op("->")("handoff").op("->>")("active") == "true",
                )
            )
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_grouped_by_state(self) -> dict[str, int]:
        async with session_scope() as session:
            statement = (
                select(SessionModel.current_state, func.count().label("count"))
                .group_by(SessionModel.current_state)
                .order_by(SessionModel.current_state.asc())
            )
            result = await session.execute(statement)
            return {state: int(count) for state, count in result.all()}
