from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from adapters.storage.repositories.lead_repo import PostgresLeadProfileRepository
from adapters.storage.repositories.session_repo import PostgresSessionRepository
from core.domain.lead import LeadProfile
from core.domain.session import Session
from tests.integration.storage.conftest import run_async


def test_session_repo_upsert_get_and_update_state(clean_session_tables: None) -> None:
    lead_id = uuid4()
    session_id = uuid4()
    now = datetime.now(UTC)

    lead_repo = PostgresLeadProfileRepository()
    session_repo = PostgresSessionRepository()

    run_async(
        lead_repo.upsert_by_phone(
            LeadProfile(
                id=lead_id,
                external_crm_id=None,
                phone="5214421234501",
                name="Cliente Uno",
                source="integration-test",
                attributes={},
                created_at=now,
                updated_at=now,
            )
        )
    )

    stored = run_async(
        session_repo.upsert(
            Session(
                id=session_id,
                lead_id=lead_id,
                current_state="new_lead",
                context={"step": "initial"},
                created_at=now,
                updated_at=now,
                last_event_at=now,
            )
        )
    )
    fetched = run_async(session_repo.get_by_lead_id(lead_id))

    assert stored.id == session_id
    assert fetched is not None
    assert fetched.current_state == "new_lead"
    assert fetched.context == {"step": "initial"}

    run_async(
        session_repo.update_state(
            session_id=session_id,
            new_state="qualified",
            context={"step": "qualified"},
        )
    )
    updated = run_async(session_repo.get_by_lead_id(lead_id))

    assert updated is not None
    assert updated.current_state == "qualified"
    assert updated.context == {"step": "qualified"}
