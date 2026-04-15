from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import SilencedUserModel
from core.ports.repositories import SilencedUserRepository


class PostgresSilencedUserRepository(SilencedUserRepository):
    async def is_silenced(self, phone: str) -> bool:
        async with session_scope() as session:
            statement = select(SilencedUserModel.phone).where(SilencedUserModel.phone == phone)
            result = await session.execute(statement)
            value = result.scalar_one_or_none()

        return value is not None

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        async with session_scope() as session:
            statement = (
                insert(SilencedUserModel)
                .values(
                    phone=phone,
                    reason=reason,
                    silenced_at=datetime.now(UTC),
                    silenced_by=silenced_by,
                )
                .on_conflict_do_update(
                    index_elements=[SilencedUserModel.phone],
                    set_={
                        "reason": reason,
                        "silenced_at": datetime.now(UTC),
                        "silenced_by": silenced_by,
                    },
                )
            )
            await session.execute(statement)

    async def unsilence(self, phone: str) -> None:
        async with session_scope() as session:
            statement = delete(SilencedUserModel).where(SilencedUserModel.phone == phone)
            await session.execute(statement)
