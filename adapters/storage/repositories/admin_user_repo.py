from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select

from adapters.storage.db import session_scope
from adapters.storage.models import AdminUserModel
from core.ports.admin_user_repository import AdminUser, AdminUserRepository


def _to_domain(model: AdminUserModel) -> AdminUser:
    return AdminUser(
        id=model.id,
        username=model.username,
        password_hash=model.password_hash,
        is_active=model.is_active,
        created_at=model.created_at,
        last_login_at=model.last_login_at,
    )


class PostgresAdminUserRepository(AdminUserRepository):
    async def get_by_id(self, user_id: UUID) -> AdminUser | None:
        async with session_scope() as session:
            result = await session.execute(
                select(AdminUserModel).where(AdminUserModel.id == user_id)
            )
            model = result.scalar_one_or_none()
        return None if model is None else _to_domain(model)

    async def get_by_username(self, username: str) -> AdminUser | None:
        async with session_scope() as session:
            result = await session.execute(
                select(AdminUserModel).where(AdminUserModel.username == username)
            )
            model = result.scalar_one_or_none()
        return None if model is None else _to_domain(model)

    async def create(self, username: str, password_hash: str) -> AdminUser:
        async with session_scope() as session:
            model = AdminUserModel(
                username=username,
                password_hash=password_hash,
                is_active=True,
            )
            session.add(model)
            await session.flush()
            await session.refresh(model)
        return _to_domain(model)

    async def update_last_login(self, user_id: UUID) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(AdminUserModel).where(AdminUserModel.id == user_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return
            model.last_login_at = datetime.now(UTC)

    async def list_all(self) -> list[AdminUser]:
        async with session_scope() as session:
            result = await session.execute(select(AdminUserModel).order_by(AdminUserModel.username))
            models = result.scalars().all()
        return [_to_domain(model) for model in models]

    async def delete(self, user_id: UUID) -> None:
        async with session_scope() as session:
            await session.execute(delete(AdminUserModel).where(AdminUserModel.id == user_id))

    async def set_active(self, user_id: UUID, is_active: bool) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(AdminUserModel).where(AdminUserModel.id == user_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return
            model.is_active = is_active

    async def update_password(self, user_id: UUID, password_hash: str) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(AdminUserModel).where(AdminUserModel.id == user_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return
            model.password_hash = password_hash
