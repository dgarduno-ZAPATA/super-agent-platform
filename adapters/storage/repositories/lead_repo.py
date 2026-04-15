from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
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
