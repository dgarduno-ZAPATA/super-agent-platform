from __future__ import annotations

from fastapi.testclient import TestClient

from core.config import get_settings


def test_upload_rejects_unsupported_file_type(client: TestClient) -> None:
    settings = get_settings()
    token_response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = token_response.json()["access_token"]

    response = client.post(
        "/api/v1/admin/knowledge/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"source_label": "Catalogo Malware"},
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported_file_type"
