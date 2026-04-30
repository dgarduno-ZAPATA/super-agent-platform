from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import insert

from adapters.storage import db as db_module
from adapters.storage.models import AdminUserModel
from api.routers import auth as auth_router
from core.config import get_settings
from core.services.admin_auth_service import pwd_context


@pytest.fixture(autouse=True)
def reset_auth_rate_limit_state() -> None:
    auth_router._ATTEMPTS_BY_IP.clear()


def test_login_with_valid_credentials_returns_token(client: TestClient) -> None:
    settings = get_settings()
    response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "access_token" in payload
    assert payload["token_type"] == "bearer"


def test_login_with_secondary_credentials_returns_token(
    client: TestClient,
) -> None:
    async def _insert_secondary() -> None:
        async with db_module.session_scope() as session:
            statement = (
                insert(AdminUserModel)
                .values(
                    username="admin2",
                    password_hash=pwd_context.hash("test-admin2-password"),
                    is_active=True,
                )
                .on_conflict_do_nothing(index_elements=[AdminUserModel.username])
            )
            await session.execute(statement)

    asyncio.run(_insert_secondary())

    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin2", "password": "test-admin2-password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "access_token" in payload
    assert payload["token_type"] == "bearer"


def test_login_with_invalid_credentials_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "invalid", "password": "invalid"},
    )

    assert response.status_code == 401


def test_protected_endpoint_without_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/stats")

    assert response.status_code == 401


def test_protected_endpoint_with_valid_token_returns_200(client: TestClient) -> None:
    settings = get_settings()
    token_response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = token_response.json()["access_token"]

    response = client.get(
        "/api/v1/dashboard/stats",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_login_blocked_after_5_failures(client: TestClient) -> None:
    settings = get_settings()
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/token",
            json={"username": settings.admin_username, "password": "wrong"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert blocked.status_code == 429


def test_login_succeeds_before_lockout_threshold(client: TestClient) -> None:
    settings = get_settings()
    for _ in range(4):
        response = client.post(
            "/api/v1/auth/token",
            json={"username": settings.admin_username, "password": "wrong"},
        )
        assert response.status_code == 401

    success = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert success.status_code == 200


def test_lockout_message_includes_wait_time(client: TestClient) -> None:
    settings = get_settings()
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/token",
            json={"username": settings.admin_username, "password": "wrong"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert "minutos" in blocked.json()["detail"]


def test_secondary_login_env_vars_do_not_grant_access_without_db_user(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_USERNAME_2", "admin2")
    monkeypatch.setenv("ADMIN_PASSWORD_2", "test-admin2-password")
    get_settings.cache_clear()

    secondary_response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin2", "password": "test-admin2-password"},
    )

    assert secondary_response.status_code == 401


def _login_and_get_token(client: TestClient) -> str:
    settings = get_settings()
    token_response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert token_response.status_code == 200
    return str(token_response.json()["access_token"])


def test_list_users_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/auth/users")
    assert response.status_code == 401


def test_create_user_success(client: TestClient) -> None:
    token = _login_and_get_token(client)
    response = client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "nuevo.admin", "password": "Password123"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["username"] == "nuevo.admin"
    assert payload["is_active"] is True
    assert "password_hash" not in payload


def test_create_user_duplicate(client: TestClient) -> None:
    token = _login_and_get_token(client)
    settings = get_settings()
    response = client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": settings.admin_username, "password": "Password123"},
    )
    assert response.status_code == 409


def test_deactivate_user(client: TestClient) -> None:
    token = _login_and_get_token(client)
    create_response = client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "temp.deactivate", "password": "Password123"},
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    deactivate_response = client.delete(
        f"/api/v1/auth/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False


def test_cannot_deactivate_self(client: TestClient) -> None:
    token = _login_and_get_token(client)
    settings = get_settings()
    users_response = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert users_response.status_code == 200
    me = next(item for item in users_response.json() if item["username"] == settings.admin_username)
    response = client.delete(
        f"/api/v1/auth/users/{me['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


def test_change_password(client: TestClient) -> None:
    admin_token = _login_and_get_token(client)
    create_response = client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "temp.password", "password": "OldPassword123"},
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    update_response = client.put(
        f"/api/v1/auth/users/{user_id}/password",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"new_password": "NewPassword123"},
    )
    assert update_response.status_code == 200

    old_login = client.post(
        "/api/v1/auth/token",
        json={"username": "temp.password", "password": "OldPassword123"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/token",
        json={"username": "temp.password", "password": "NewPassword123"},
    )
    assert new_login.status_code == 200
