from __future__ import annotations

from fastapi.testclient import TestClient

from core.config import get_settings


def test_brand_config_endpoint_returns_brand_fields(client: TestClient) -> None:
    settings = get_settings()
    token_response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = token_response.json()["access_token"]

    response = client.get("/brand/config", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert "name" in payload
    assert "primary_color" in payload
    assert "slug" in payload
    assert "api_key" not in payload
    assert "database_url" not in payload
