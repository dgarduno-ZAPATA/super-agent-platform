from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.brand.loader import load_brand
from core.domain.lead import LeadProfile
from core.services.campaign_agent import CampaignAgent


class FakeLeadProfileRepository:
    def __init__(self, leads: list[LeadProfile]) -> None:
        self.leads = leads
        self.calls: list[tuple[int, int]] = []

    async def get_dormant_leads(self, days_inactive: int, limit: int = 100) -> list[LeadProfile]:
        self.calls.append((days_inactive, limit))
        return self.leads[:limit]


class FakeOutboundQueueRepository:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []

    async def enqueue(
        self,
        lead_id: UUID,
        campaign_id: UUID | None,
        payload: dict[str, object],
        priority: int,
        scheduled_at: datetime,
    ) -> UUID:
        item_id = uuid4()
        self.enqueued.append(
            {
                "id": item_id,
                "lead_id": lead_id,
                "campaign_id": campaign_id,
                "payload": payload,
                "priority": priority,
                "scheduled_at": scheduled_at,
            }
        )
        return item_id


def _lead(phone: str, name: str) -> LeadProfile:
    now = datetime.now(UTC) - timedelta(days=120)
    return LeadProfile(
        id=uuid4(),
        external_crm_id=None,
        phone=phone,
        name=name,
        source="crm",
        attributes={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_schedule_campaign_enqueues_p1_messages() -> None:
    brand = load_brand(Path("brand"))
    lead_repo = FakeLeadProfileRepository(
        leads=[
            _lead("5214421234501", "Cliente Uno"),
            _lead("5214421234502", "Cliente Dos"),
        ]
    )
    queue_repo = FakeOutboundQueueRepository()
    agent = CampaignAgent(
        lead_profile_repository=lead_repo,
        outbound_queue_repository=queue_repo,
        brand=brand,
    )

    await agent.schedule_campaign("reactivacion_general")

    assert len(queue_repo.enqueued) == 2
    assert lead_repo.calls[0][0] == 90
    assert queue_repo.enqueued[0]["priority"] == 1
    payload = queue_repo.enqueued[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["campaign_key"] == "reactivacion_general"
    assert "Raúl" in str(payload["text"])
