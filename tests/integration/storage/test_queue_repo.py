from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from adapters.storage.db import session_scope
from adapters.storage.repositories.lead_repo import PostgresLeadProfileRepository
from adapters.storage.repositories.outbound_queue_repo import PostgresOutboundQueueRepository
from core.domain.lead import LeadProfile
from tests.integration.storage.conftest import run_async


def _cleanup_tables() -> None:
    async def _delete_rows() -> None:
        async with session_scope() as session:
            await session.execute(text("DELETE FROM outbound_queue"))
            await session.execute(text("DELETE FROM lead_profiles"))

    run_async(_delete_rows())


def _insert_lead(phone: str) -> LeadProfile:
    repo = PostgresLeadProfileRepository()
    now = datetime.now(UTC)
    return run_async(
        repo.upsert_by_phone(
            LeadProfile(
                id=uuid4(),
                external_crm_id=None,
                phone=phone,
                name="Lead Test",
                source="integration",
                attributes={},
                created_at=now,
                updated_at=now,
            )
        )
    )


def test_get_next_batch_respects_priority_and_schedule(clean_event_tables: None) -> None:
    _cleanup_tables()
    lead = _insert_lead("5214429990001")
    repo = PostgresOutboundQueueRepository()
    now = datetime.now(UTC)

    run_async(
        repo.enqueue(
            lead_id=lead.id,
            campaign_id=None,
            payload={"text": "mensaje p1"},
            priority=1,
            scheduled_at=now - timedelta(minutes=5),
        )
    )
    run_async(
        repo.enqueue(
            lead_id=lead.id,
            campaign_id=None,
            payload={"text": "mensaje p0"},
            priority=0,
            scheduled_at=now - timedelta(minutes=2),
        )
    )
    run_async(
        repo.enqueue(
            lead_id=lead.id,
            campaign_id=None,
            payload={"text": "mensaje futuro"},
            priority=0,
            scheduled_at=now + timedelta(minutes=20),
        )
    )

    batch = run_async(repo.get_next_batch(limit=10))

    assert len(batch) == 2
    assert batch[0].priority == 0
    assert batch[0].payload["text"] == "mensaje p0"
    assert batch[1].priority == 1
    assert batch[1].payload["text"] == "mensaje p1"
