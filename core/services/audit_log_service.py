from __future__ import annotations

import structlog

from adapters.storage.repositories.audit_log_repo import PostgresAuditLogRepository

logger = structlog.get_logger("super_agent_platform.audit_log")


class AuditLogService:
    def __init__(self, repo: PostgresAuditLogRepository) -> None:
        self.repo = repo

    async def log(
        self,
        actor: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, object] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Fire-and-forget: nunca bloquea el flujo principal."""
        try:
            await self.repo.insert(
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details or {},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("audit_log_write_failed", error=str(exc), action=action)
