from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from adapters.storage.db import session_scope
from adapters.storage.repositories.lead_repo import PostgresLeadProfileRepository
from adapters.storage.repositories.session_repo import PostgresSessionRepository
from core.domain.lead import LeadProfile
from core.domain.session import Session
from tests.integration.api.conftest import run_async


def _seed_lead_and_session(lead_id: UUID, state: str) -> None:
    async def _insert() -> None:
        now = datetime.now(UTC)
        lead_repo = PostgresLeadProfileRepository()
        session_repo = PostgresSessionRepository()
        phone_suffix = str(int(lead_id.int % 10_000_000_000)).zfill(10)
        phone = f"521{phone_suffix}"

        await lead_repo.upsert_by_phone(
            LeadProfile(
                id=lead_id,
                external_crm_id=None,
                phone=phone,
                name="Lead API Integration",
                source="integration-test",
                attributes={"seeded_for": "conversations_api"},
                created_at=now,
                updated_at=now,
            )
        )
        await session_repo.upsert(
            Session(
                id=uuid4(),
                lead_id=lead_id,
                current_state=state,
                context={},
                created_at=now,
                updated_at=now,
                last_event_at=now,
            )
        )

    run_async(_insert())


def _session_state(lead_id: UUID) -> str | None:
    async def _query() -> str | None:
        async with session_scope() as session:
            result = await session.execute(
                text("""
                    SELECT current_state
                    FROM sessions
                    WHERE lead_id = :lead_id
                    """),
                {"lead_id": lead_id},
            )
            value = result.scalar_one_or_none()
            return value if isinstance(value, str) else None

    return run_async(_query())


def _system_event_count(lead_id: UUID, event_type: str) -> int:
    async def _query() -> int:
        async with session_scope() as session:
            result = await session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM conversation_events
                    WHERE lead_id = :lead_id
                    AND event_type = :event_type
                    """),
                {"lead_id": lead_id, "event_type": event_type},
            )
            return int(result.scalar_one())

    return run_async(_query())


def test_take_control_endpoint_returns_200_and_updates_session(client: TestClient) -> None:
    lead_id = uuid4()
    _seed_lead_and_session(lead_id=lead_id, state="handoff_pending")

    response = client.post(f"/api/v1/conversations/{lead_id}/take-control")

    assert response.status_code == 200
    assert response.json()["lead_id"] == str(lead_id)
    assert response.json()["state"] == "handoff_active"
    assert _session_state(lead_id) == "handoff_active"
    assert _system_event_count(lead_id, "system_agent_took_control") == 1


def test_release_control_endpoint_returns_200_and_updates_session(client: TestClient) -> None:
    lead_id = uuid4()
    _seed_lead_and_session(lead_id=lead_id, state="handoff_active")

    response = client.post(f"/api/v1/conversations/{lead_id}/release-control")

    assert response.status_code == 200
    assert response.json()["lead_id"] == str(lead_id)
    assert response.json()["state"] == "idle"
    assert _session_state(lead_id) == "idle"
    assert _system_event_count(lead_id, "system_agent_released_control") == 1


def test_take_control_endpoint_returns_404_when_lead_has_no_session(client: TestClient) -> None:
    missing_lead_id = uuid4()

    response = client.post(f"/api/v1/conversations/{missing_lead_id}/take-control")

    assert response.status_code == 404


def test_release_control_endpoint_returns_404_when_lead_has_no_session(client: TestClient) -> None:
    missing_lead_id = uuid4()

    response = client.post(f"/api/v1/conversations/{missing_lead_id}/release-control")

    assert response.status_code == 404
