from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import LeadProfileModel
from core.domain.lead import LeadProfile
from core.ports.repositories import LeadProfileRepository


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _to_domain(model: LeadProfileModel) -> LeadProfile:
    return LeadProfile(
        id=model.id,
        external_crm_id=model.external_crm_id,
        phone=model.phone,
        name=model.name,
        source=model.source,
        attributes=model.attributes,
        created_at=_ensure_utc(model.created_at),
        updated_at=_ensure_utc(model.updated_at),
    )


class PostgresLeadProfileRepository(LeadProfileRepository):
    async def get_by_id(self, lead_id: UUID) -> LeadProfile | None:
        async with session_scope() as session:
            statement = select(LeadProfileModel).where(LeadProfileModel.id == lead_id)
            result = await session.execute(statement)
            model = result.scalar_one_or_none()

        return None if model is None else _to_domain(model)

    async def get_by_phone(self, phone: str) -> LeadProfile | None:
        async with session_scope() as session:
            statement = select(LeadProfileModel).where(LeadProfileModel.phone == phone)
            result = await session.execute(statement)
            model = result.scalar_one_or_none()

        return None if model is None else _to_domain(model)

    async def upsert_by_phone(self, profile: LeadProfile) -> LeadProfile:
        async with session_scope() as session:
            statement = (
                insert(LeadProfileModel)
                .values(
                    id=profile.id,
                    external_crm_id=profile.external_crm_id,
                    phone=profile.phone,
                    name=profile.name,
                    source=profile.source,
                    attributes=profile.attributes,
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=[LeadProfileModel.phone],
                    set_={
                        "external_crm_id": profile.external_crm_id,
                        "name": profile.name,
                        "source": profile.source,
                        "metadata": profile.attributes,
                        "updated_at": profile.updated_at,
                    },
                )
                .returning(LeadProfileModel)
            )
            result = await session.execute(statement)
            model = result.scalar_one()

        return _to_domain(model)

    async def get_dormant_leads(self, days_inactive: int, limit: int = 100) -> list[LeadProfile]:
        threshold = datetime.now(UTC) - timedelta(days=days_inactive)

        async with session_scope() as session:
            statement = (
                select(LeadProfileModel)
                .where(LeadProfileModel.updated_at <= threshold)
                .order_by(LeadProfileModel.updated_at.asc())
                .limit(limit)
            )
            result = await session.execute(statement)
            models = result.scalars().all()

        return [_to_domain(model) for model in models]

    async def count_total(self) -> int:
        async with session_scope() as session:
            statement = select(func.count()).select_from(LeadProfileModel)
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_created_since(self, since: datetime) -> int:
        async with session_scope() as session:
            statement = (
                select(func.count())
                .select_from(LeadProfileModel)
                .where(LeadProfileModel.created_at >= since)
            )
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_grouped_by_stage(self) -> dict[str, int]:
        stage_expr = func.coalesce(
            LeadProfileModel.attributes.op("->>")("crm_stage"),
            LeadProfileModel.attributes.op("->>")("stage"),
            "unknown",
        )
        async with session_scope() as session:
            statement = (
                select(stage_expr.label("stage"), func.count().label("count"))
                .select_from(LeadProfileModel)
                .group_by(stage_expr)
                .order_by(stage_expr.asc())
            )
            result = await session.execute(statement)
            return {stage: int(count) for stage, count in result.all()}
