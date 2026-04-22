from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.routers import auth as auth_router
from core.config import get_settings


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
