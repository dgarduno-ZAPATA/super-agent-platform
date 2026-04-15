from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from adapters.storage.repositories.lead_repo import PostgresLeadProfileRepository
from core.domain.lead import LeadProfile
from tests.integration.storage.conftest import run_async


def test_lead_repo_upsert_get_and_idempotency(clean_lead_tables: None) -> None:
    repo = PostgresLeadProfileRepository()
    original_id = uuid4()
    now = datetime.now(UTC)

    stored = run_async(
        repo.upsert_by_phone(
            LeadProfile(
                id=original_id,
                external_crm_id="crm-001",
                phone="5214421234502",
                name="Cliente Dos",
                source="landing-page",
                attributes={"interest": "cascadia"},
                created_at=now,
                updated_at=now,
            )
        )
    )
    updated = run_async(
        repo.upsert_by_phone(
            LeadProfile(
                id=uuid4(),
                external_crm_id="crm-001",
                phone="5214421234502",
                name="Cliente Dos Actualizado",
                source="landing-page",
                attributes={"interest": "lt"},
                created_at=now,
                updated_at=datetime.now(UTC),
            )
        )
    )
    fetched = run_async(repo.get_by_phone("5214421234502"))

    assert stored.id == original_id
    assert updated.id == original_id
    assert fetched is not None
    assert fetched.id == original_id
    assert fetched.name == "Cliente Dos Actualizado"
    assert fetched.attributes == {"interest": "lt"}
