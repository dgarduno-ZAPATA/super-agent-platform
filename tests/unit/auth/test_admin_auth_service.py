from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.ports.admin_user_repository import AdminUser
from core.services.admin_auth_service import AdminAuthService


class FakeAdminUserRepository:
    def __init__(self, user: AdminUser | None) -> None:
        self._user = user

    async def get_by_username(self, username: str) -> AdminUser | None:
        if self._user is None:
            return None
        return self._user if self._user.username == username else None

    async def create(self, username: str, password_hash: str) -> AdminUser:
        now = datetime.now(UTC)
        created = AdminUser(
            id=uuid4(),
            username=username,
            password_hash=password_hash,
            is_active=True,
            created_at=now,
            last_login_at=None,
        )
        self._user = created
        return created

    async def update_last_login(self, user_id):  # type: ignore[no-untyped-def]
        return None

    async def list_all(self) -> list[AdminUser]:
        return [] if self._user is None else [self._user]

    async def delete(self, user_id):  # type: ignore[no-untyped-def]
        return None

    async def update_password(self, user_id, password_hash: str):  # type: ignore[no-untyped-def]
        return None


def _admin_user(username: str, password_hash: str, is_active: bool = True) -> AdminUser:
    now = datetime.now(UTC)
    return AdminUser(
        id=uuid4(),
        username=username,
        password_hash=password_hash,
        is_active=is_active,
        created_at=now,
        last_login_at=None,
    )


def test_hash_and_verify() -> None:
    service = AdminAuthService(repo=FakeAdminUserRepository(user=None))
    hashed = service.hash_password("Zapata2026Admin")
    assert service.verify_password("Zapata2026Admin", hashed) is True


def test_verify_wrong_password() -> None:
    service = AdminAuthService(repo=FakeAdminUserRepository(user=None))
    hashed = service.hash_password("Zapata2026Admin")
    assert service.verify_password("otro-password", hashed) is False


@pytest.mark.asyncio
async def test_authenticate_success() -> None:
    base_service = AdminAuthService(repo=FakeAdminUserRepository(user=None))
    user = _admin_user("admin", base_service.hash_password("Zapata2026Admin"))
    service = AdminAuthService(repo=FakeAdminUserRepository(user=user))

    authenticated = await service.authenticate("admin", "Zapata2026Admin")

    assert authenticated == user


@pytest.mark.asyncio
async def test_authenticate_wrong_password() -> None:
    base_service = AdminAuthService(repo=FakeAdminUserRepository(user=None))
    user = _admin_user("admin", base_service.hash_password("Zapata2026Admin"))
    service = AdminAuthService(repo=FakeAdminUserRepository(user=user))

    authenticated = await service.authenticate("admin", "incorrecta")

    assert authenticated is None


@pytest.mark.asyncio
async def test_authenticate_inactive_user() -> None:
    base_service = AdminAuthService(repo=FakeAdminUserRepository(user=None))
    user = _admin_user("admin", base_service.hash_password("Zapata2026Admin"), is_active=False)
    service = AdminAuthService(repo=FakeAdminUserRepository(user=user))

    authenticated = await service.authenticate("admin", "Zapata2026Admin")

    assert authenticated is None


@pytest.mark.asyncio
async def test_authenticate_user_not_found() -> None:
    service = AdminAuthService(repo=FakeAdminUserRepository(user=None))

    authenticated = await service.authenticate("admin", "Zapata2026Admin")

    assert authenticated is None
