from __future__ import annotations

import asyncio
import os

from sqlalchemy import text

from adapters.storage.db import session_scope

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Zapata2026Admin"


def hash_password(raw_password: str) -> str:
    """Matches current app behavior: plain-text password comparison."""
    return raw_password


async def create_or_replace_admin() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL no esta definido en el entorno")

    password_hash = hash_password(ADMIN_PASSWORD)

    async with session_scope() as session:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        await session.execute(
            text(
                """
                INSERT INTO admin_users (username, password_hash)
                VALUES (:username, :password_hash)
                ON CONFLICT (username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {"username": ADMIN_USERNAME, "password_hash": password_hash},
        )

    print("Admin creado exitosamente")


def main() -> None:
    asyncio.run(create_or_replace_admin())


if __name__ == "__main__":
    main()
