from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import LeadProfileModel, OutboundQueueModel
from core.domain.outbound_queue import OutboundQueueItem
from core.ports.repositories import OutboundQueueRepository


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _to_domain(model: OutboundQueueModel, lead_phone: str | None = None) -> OutboundQueueItem:
    campaign_id: UUID | None = None
    if model.campaign_id:
        try:
            campaign_id = UUID(model.campaign_id)
        except ValueError:
            campaign_id = None

    return OutboundQueueItem(
        id=model.id,
        lead_id=model.lead_id,
        lead_phone=lead_phone,
        campaign_id=campaign_id,
        priority=model.priority,
        payload=model.payload,
        status=model.status,
        scheduled_at=_ensure_utc(model.scheduled_at),
        sent_at=_ensure_utc(model.sent_at) if model.sent_at is not None else None,
        attempts=model.attempts,
        last_error=model.last_error,
    )


class PostgresOutboundQueueRepository(OutboundQueueRepository):
    async def enqueue(
        self,
        lead_id: UUID,
        campaign_id: UUID | None,
        payload: dict[str, object],
        priority: int,
        scheduled_at: datetime,
    ) -> UUID:
        item_id = uuid4()
        async with session_scope() as session:
            statement = (
                insert(OutboundQueueModel)
                .values(
                    id=item_id,
                    lead_id=lead_id,
                    campaign_id=str(campaign_id) if campaign_id is not None else None,
                    priority=priority,
                    payload=payload,
                    status="pending",
                    scheduled_at=scheduled_at,
                    attempts=0,
                )
                .returning(OutboundQueueModel.id)
            )
            result = await session.execute(statement)
            created_id = result.scalar_one()

        return created_id

    async def get_next_batch(self, limit: int = 10) -> list[OutboundQueueItem]:
        now = datetime.now(UTC)
        async with session_scope() as session:
            statement = (
                select(OutboundQueueModel)
                .where(
                    OutboundQueueModel.status == "pending",
                    OutboundQueueModel.scheduled_at <= now,
                )
                .order_by(OutboundQueueModel.priority.asc(), OutboundQueueModel.scheduled_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
            result = await session.execute(statement)
            models = result.scalars().all()

            lead_ids = [model.lead_id for model in models if model.lead_id is not None]
            phone_by_lead_id: dict[UUID, str] = {}
            if lead_ids:
                leads_result = await session.execute(
                    select(LeadProfileModel.id, LeadProfileModel.phone).where(
                        LeadProfileModel.id.in_(lead_ids)
                    )
                )
                phone_by_lead_id = {lead_id: phone for lead_id, phone in leads_result.all()}

            items: list[OutboundQueueItem] = []
            for model in models:
                model.status = "processing"
                model.attempts = model.attempts + 1
                lead_phone = (
                    phone_by_lead_id.get(model.lead_id) if model.lead_id is not None else None
                )
                items.append(_to_domain(model, lead_phone=lead_phone))

        return items

    async def mark_as_sent(self, item_id: UUID) -> None:
        async with session_scope() as session:
            statement = select(OutboundQueueModel).where(OutboundQueueModel.id == item_id)
            result = await session.execute(statement)
            model = result.scalar_one_or_none()
            if model is None:
                return

            model.status = "sent"
            model.sent_at = datetime.now(UTC)
            model.last_error = None

    async def mark_as_failed(self, item_id: UUID, error: str) -> None:
        async with session_scope() as session:
            statement = select(OutboundQueueModel).where(OutboundQueueModel.id == item_id)
            result = await session.execute(statement)
            model = result.scalar_one_or_none()
            if model is None:
                return

            model.status = "failed"
            model.last_error = error

    async def count_by_priority_and_status(
        self, priorities: set[int], statuses: set[str]
    ) -> dict[int, dict[str, int]]:
        counts: dict[int, dict[str, int]] = {}
        if not priorities or not statuses:
            return counts

        async with session_scope() as session:
            statement = (
                select(
                    OutboundQueueModel.priority,
                    OutboundQueueModel.status,
                    func.count().label("count"),
                )
                .where(
                    OutboundQueueModel.priority.in_(priorities),
                    OutboundQueueModel.status.in_(statuses),
                )
                .group_by(OutboundQueueModel.priority, OutboundQueueModel.status)
            )
            result = await session.execute(statement)
            for priority, status, count in result.all():
                if priority not in counts:
                    counts[priority] = {}
                counts[priority][status] = int(count)

        return counts
