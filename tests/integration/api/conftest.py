from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from typing import TypeVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from adapters.storage import db as db_module
from adapters.storage.models import AdminUserModel
from api.main import create_app
from api.routers import auth as auth_router
from core.config import get_settings
from core.services.admin_auth_service import pwd_context

DEFAULT_HOST_DATABASE_URL = (
    "postgresql+asyncpg://app_user:change_me@127.0.0.1:5432/super_agent_platform"
)
ResultT = TypeVar("ResultT")


def run_async(operation: Awaitable[ResultT]) -> ResultT:
    return asyncio.run(operation)


@pytest.fixture(scope="session", autouse=True)
def configure_test_database_url() -> None:
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL", DEFAULT_HOST_DATABASE_URL
    )
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def async_engine_for_test() -> AsyncEngine:
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        isolation_level="SERIALIZABLE",
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    db_module._engine = engine
    db_module._session_factory = session_factory

    yield engine

    run_async(engine.dispose())
    db_module._engine = None
    db_module._session_factory = None


@pytest.fixture(autouse=True)
def clean_webhook_tables(async_engine_for_test: AsyncEngine) -> None:
    async def _delete_rows() -> None:
        async with db_module.session_scope() as session:
            for table_name in [
                "crm_dlq",
                "crm_outbox",
                "knowledge_chunks",
                "knowledge_sources",
                "admin_users",
                "admin_totp",
                "login_attempts",
                "audit_log",
                "conversation_events",
                "outbound_queue",
                "sessions",
                "silenced_users",
                "lead_profiles",
            ]:
                await session.execute(text(f"DELETE FROM {table_name}"))

    run_async(_delete_rows())


@pytest.fixture(autouse=True)
def set_test_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-32-chars-minimum")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-evolution-key")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    get_settings.cache_clear()
    auth_router._ATTEMPTS_BY_IP.clear()


@pytest.fixture(autouse=True)
def seed_admin_users(
    clean_webhook_tables: None,
    set_test_env_vars: None,
) -> None:
    del clean_webhook_tables
    del set_test_env_vars

    async def _seed() -> None:
        username = os.environ["ADMIN_USERNAME"]
        password = os.environ["ADMIN_PASSWORD"]
        password_hash = pwd_context.hash(password)
        async with db_module.session_scope() as session:
            statement = (
                insert(AdminUserModel)
                .values(
                    username=username,
                    password_hash=password_hash,
                    is_active=True,
                )
                .on_conflict_do_nothing(index_elements=[AdminUserModel.username])
            )
            await session.execute(statement)

    run_async(_seed())


@pytest.fixture
def client(seed_admin_users: None) -> TestClient:
    del seed_admin_users
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
