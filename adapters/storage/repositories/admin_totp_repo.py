from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import AdminTOTPModel


@dataclass(frozen=True, slots=True)
class AdminTOTPRecord:
    id: UUID
    username: str
    totp_secret: str
    enabled: bool


def _to_domain(model: AdminTOTPModel) -> AdminTOTPRecord:
    return AdminTOTPRecord(
        id=model.id,
        username=model.username,
        totp_secret=model.totp_secret,
        enabled=model.enabled,
    )


class PostgresAdminTOTPRepository:
    async def upsert(self, username: str, secret: str, enabled: bool = False) -> None:
        async with session_scope() as session:
            statement = insert(AdminTOTPModel).values(
                username=username,
                totp_secret=secret,
                enabled=enabled,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[AdminTOTPModel.username],
                set_={
                    "totp_secret": secret,
                    "enabled": enabled,
                },
            )
            await session.execute(statement)

    async def get(self, username: str) -> AdminTOTPRecord | None:
        async with session_scope() as session:
            result = await session.execute(
                select(AdminTOTPModel).where(AdminTOTPModel.username == username)
            )
            model = result.scalar_one_or_none()
        return None if model is None else _to_domain(model)

    async def enable(self, username: str) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(AdminTOTPModel).where(AdminTOTPModel.username == username)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return
            model.enabled = True
