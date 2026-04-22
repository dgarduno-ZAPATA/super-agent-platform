from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient

from adapters.storage.repositories.admin_totp_repo import PostgresAdminTOTPRepository
from core.auth.jwt_handler import create_access_token
from core.config import get_settings
from tests.integration.api.conftest import run_async


def _login_password_only(client: TestClient) -> dict[str, object]:
    settings = get_settings()
    response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert response.status_code == 200
    return response.json()


def _enable_2fa(client: TestClient) -> dict[str, object]:
    base_login = _login_password_only(client)
    access_token = str(base_login["access_token"])
    headers = {"Authorization": f"Bearer {access_token}"}

    setup_response = client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup_response.status_code == 200
    setup_payload = setup_response.json()
    secret = str(setup_payload["secret"])
    code = pyotp.TOTP(secret).now()

    confirm_response = client.post(
        "/api/v1/auth/2fa/confirm",
        headers=headers,
        json={"code": code},
    )
    assert confirm_response.status_code == 200
    return setup_payload


def test_2fa_setup_returns_valid_qr_and_secret(client: TestClient) -> None:
    login_payload = _login_password_only(client)
    headers = {"Authorization": f"Bearer {login_payload['access_token']}"}

    response = client.post("/api/v1/auth/2fa/setup", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["qr_code"].startswith("data:image/png;base64,")
    assert isinstance(payload["secret"], str)
    assert len(payload["secret"]) >= 16


def test_2fa_confirm_accepts_valid_totp_code(client: TestClient) -> None:
    login_payload = _login_password_only(client)
    headers = {"Authorization": f"Bearer {login_payload['access_token']}"}
    setup_payload = client.post("/api/v1/auth/2fa/setup", headers=headers).json()
    code = pyotp.TOTP(str(setup_payload["secret"])).now()

    response = client.post("/api/v1/auth/2fa/confirm", headers=headers, json={"code": code})
    status_response = client.get("/api/v1/auth/2fa/status", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "2fa_enabled"
    assert status_response.status_code == 200
    assert status_response.json()["enabled"] is True


def test_2fa_confirm_rejects_invalid_code(client: TestClient) -> None:
    login_payload = _login_password_only(client)
    headers = {"Authorization": f"Bearer {login_payload['access_token']}"}
    client.post("/api/v1/auth/2fa/setup", headers=headers)

    response = client.post("/api/v1/auth/2fa/confirm", headers=headers, json={"code": "000000"})

    assert response.status_code == 400


def test_login_returns_pre_auth_when_2fa_enabled(client: TestClient) -> None:
    _enable_2fa(client)
    payload = _login_password_only(client)

    assert payload["requires_2fa"] is True
    assert "pre_auth_token" in payload
    assert "access_token" not in payload


def test_2fa_login_completes_with_valid_code(client: TestClient) -> None:
    setup_payload = _enable_2fa(client)
    login_payload = _login_password_only(client)
    code = pyotp.TOTP(str(setup_payload["secret"])).now()

    response = client.post(
        "/api/v1/auth/2fa/login",
        json={"pre_auth_token": login_payload["pre_auth_token"], "code": code},
    )

    assert response.status_code == 200
    final_payload = response.json()
    assert "access_token" in final_payload
    assert final_payload["token_type"] == "bearer"


def test_2fa_login_rejects_expired_pre_auth_token(client: TestClient) -> None:
    _enable_2fa(client)
    settings = get_settings()
    expired = create_access_token(
        {"sub": settings.admin_username, "stage": "pre_auth"},
        expires_minutes=-1,
    )
    record = run_async(PostgresAdminTOTPRepository().get(settings.admin_username))
    assert record is not None
    code = pyotp.TOTP(record.totp_secret).now()

    response = client.post(
        "/api/v1/auth/2fa/login",
        json={"pre_auth_token": expired, "code": code},
    )

    assert response.status_code == 401


def test_login_still_works_single_step_when_2fa_disabled(client: TestClient) -> None:
    payload = _login_password_only(client)

    assert payload["requires_2fa"] is False
    assert "access_token" in payload
