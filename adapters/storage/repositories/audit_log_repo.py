from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import AuditLogModel


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class PostgresAuditLogRepository:
    async def insert(
        self,
        actor: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, object] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UUID:
        async with session_scope() as session:
            statement = (
                insert(AuditLogModel)
                .values(
                    actor=actor,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details or {},
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                .returning(AuditLogModel.id)
            )
            result = await session.execute(statement)
            return result.scalar_one()

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        action: str | None = None,
    ) -> list[dict[str, object]]:
        safe_limit = max(1, min(limit, 200))
        safe_offset = max(0, offset)

        async with session_scope() as session:
            statement = select(AuditLogModel)
            if action:
                statement = statement.where(AuditLogModel.action == action)
            statement = (
                statement.order_by(AuditLogModel.timestamp.desc())
                .limit(safe_limit)
                .offset(safe_offset)
            )
            rows = (await session.execute(statement)).scalars().all()

        return [
            {
                "id": str(row.id),
                "timestamp": _ensure_utc(row.timestamp).isoformat(),
                "actor": row.actor,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "details": dict(row.details or {}),
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
            }
            for row in rows
        ]
