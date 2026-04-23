from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import LoginAttemptModel


class PostgresLoginAttemptRepository:
    async def insert(self, ip: str, username: str | None, success: bool) -> UUID:
        async with session_scope() as session:
            statement = (
                insert(LoginAttemptModel)
                .values(ip_address=ip, username=username, success=success)
                .returning(LoginAttemptModel.id)
            )
            result = await session.execute(statement)
            return result.scalar_one()

    async def count_failures_since(self, ip: str, since: datetime) -> int:
        async with session_scope() as session:
            statement = (
                select(func.count())
                .select_from(LoginAttemptModel)
                .where(
                    LoginAttemptModel.ip_address == ip,
                    LoginAttemptModel.success.is_(False),
                    LoginAttemptModel.attempted_at >= since,
                )
            )
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def oldest_failure_since(self, ip: str, since: datetime) -> datetime | None:
        async with session_scope() as session:
            statement = select(func.min(LoginAttemptModel.attempted_at)).where(
                LoginAttemptModel.ip_address == ip,
                LoginAttemptModel.success.is_(False),
                LoginAttemptModel.attempted_at >= since,
            )
            result = await session.execute(statement)
            value = result.scalar_one_or_none()
            return value if isinstance(value, datetime) else None
