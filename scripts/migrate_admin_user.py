from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy.dialects.postgresql import insert

from adapters.storage.db import session_scope
from adapters.storage.models import AdminUserModel
from adapters.storage.repositories.admin_user_repo import PostgresAdminUserRepository
from core.services.admin_auth_service import AdminAuthService


async def _create_admin_user(username: str, password: str) -> bool:
    if not username or not password:
        raise ValueError("username/password vacios")

    auth_service = AdminAuthService(repo=PostgresAdminUserRepository())
    password_hash = auth_service.hash_password(password)

    async with session_scope() as session:
        statement = (
            insert(AdminUserModel)
            .values(
                username=username,
                password_hash=password_hash,
                is_active=True,
            )
            .on_conflict_do_nothing(index_elements=[AdminUserModel.username])
            .returning(AdminUserModel.id)
        )
        result = await session.execute(statement)
        inserted_id = result.scalar_one_or_none()

    if inserted_id is None:
        return False
    return True


async def migrate_admin_user_from_env() -> None:
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")

    if not username or not password:
        print("ADMIN_USERNAME/ADMIN_PASSWORD no definidos; no se migraron usuarios.")
        return

    created = await _create_admin_user(username=username, password=password)
    if created:
        print(f"Usuario admin '{username}' migrado exitosamente.")
    else:
        print(f"Usuario admin '{username}' ya existia. Sin cambios.")


async def migrate_admin_user_from_args(username: str, password: str) -> None:
    created = await _create_admin_user(username=username.strip(), password=password)
    if created:
        print(f"Usuario admin '{username.strip()}' creado exitosamente.")
    else:
        print(f"Usuario admin '{username.strip()}' ya existia. Sin cambios.")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 0:
        asyncio.run(migrate_admin_user_from_env())
        return

    if len(args) == 2:
        username, password = args
        if not username.strip() or not password:
            raise SystemExit("Uso: python scripts/migrate_admin_user.py [username password]")
        asyncio.run(migrate_admin_user_from_args(username=username, password=password))
        return

    raise SystemExit("Uso: python scripts/migrate_admin_user.py [username password]")


if __name__ == "__main__":
    main()
