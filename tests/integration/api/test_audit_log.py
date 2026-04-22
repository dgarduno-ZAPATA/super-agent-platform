from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from adapters.storage.db import session_scope
from adapters.storage.repositories.audit_log_repo import PostgresAuditLogRepository
from core.config import get_settings
from tests.integration.api.conftest import run_async


def _issue_token(client: TestClient) -> str:
    settings = get_settings()
    token_response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    return token_response.json()["access_token"]


def _count_by_action(action: str) -> int:
    async def _query() -> int:
        async with session_scope() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM audit_log WHERE action = :action"),
                {"action": action},
            )
            return int(result.scalar_one())

    return run_async(_query())


def _seed_entry(action: str, resource_id: str) -> None:
    async def _insert() -> None:
        repo = PostgresAuditLogRepository()
        await repo.insert(
            actor="admin",
            action=action,
            resource_type="knowledge_source",
            resource_id=resource_id,
            details={"seeded": True, "at": datetime.now(UTC).isoformat(), "id": str(uuid4())},
            ip_address="127.0.0.1",
            user_agent="pytest",
        )

    run_async(_insert())


def test_audit_log_records_login_success(client: TestClient) -> None:
    before = _count_by_action("login_success")
    _issue_token(client)
    after = _count_by_action("login_success")
    assert after == before + 1


def test_audit_log_endpoint_returns_entries(client: TestClient) -> None:
    _seed_entry(action="knowledge_upload", resource_id="Catalogo Q1")
    token = _issue_token(client)

    response = client.get(
        "/admin/audit-log?limit=50&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("entries"), list)
    assert payload["limit"] == 50
    assert payload["offset"] == 0


def test_audit_log_filters_by_action(client: TestClient) -> None:
    _seed_entry(action="knowledge_upload", resource_id="A")
    _seed_entry(action="knowledge_delete", resource_id="B")
    token = _issue_token(client)

    response = client.get(
        "/admin/audit-log?limit=50&offset=0&action=knowledge_delete",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    entries = payload["entries"]
    assert len(entries) >= 1
    assert all(item["action"] == "knowledge_delete" for item in entries)
