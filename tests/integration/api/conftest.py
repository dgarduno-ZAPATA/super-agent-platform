from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from typing import TypeVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from adapters.storage import db as db_module
from api.main import create_app
from core.config import get_settings

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
                "conversation_events",
                "outbound_queue",
                "sessions",
                "silenced_users",
                "lead_profiles",
            ]:
                await session.execute(text(f"DELETE FROM {table_name}"))

    run_async(_delete_rows())


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
