from fastapi.testclient import TestClient

from api.main import app


def test_healthcheck_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "super-agent-platform"
    assert isinstance(payload["inventory_count"], int)
    assert payload["inventory_count"] >= 0
    assert response.headers["X-Request-ID"]
