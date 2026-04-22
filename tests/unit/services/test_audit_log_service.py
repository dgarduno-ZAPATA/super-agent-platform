from __future__ import annotations

from unittest.mock import AsyncMock

from core.services.audit_log_service import AuditLogService


async def test_audit_log_fire_and_forget_never_raises() -> None:
    repo = AsyncMock()
    repo.insert.side_effect = RuntimeError("db unavailable")
    service = AuditLogService(repo=repo)

    await service.log(
        actor="admin",
        action="login_success",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    repo.insert.assert_awaited_once()
