from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from adapters.storage.db import session_scope
from tests.integration.api.conftest import run_async


def _valid_text_payload(message_id: str = "wamid-001") -> dict[str, object]:
    return {
        "event": "messages.upsert",
        "instance": "selectrucks-zapata",
        "data": {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": message_id,
                "fromMe": False,
            },
            "messageType": "conversation",
            "message": {"conversation": "Hola desde integration"},
            "pushName": "Cliente Integration",
            "messageTimestamp": 1713200000,
            "instanceId": "instance-1",
            "source": "android",
        },
    }


def _event_count_by_message_id(message_id: str) -> int:
    async def _query() -> int:
        async with session_scope() as session:
            result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM conversation_events
                    WHERE payload ->> 'message_id' = :message_id
                    """
                ),
                {"message_id": message_id},
            )
            return int(result.scalar_one())

    return run_async(_query())


def _total_event_count() -> int:
    async def _query() -> int:
        async with session_scope() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM conversation_events"))
            return int(result.scalar_one())

    return run_async(_query())


def test_post_webhook_valid_payload_returns_200_and_persists_event(client: TestClient) -> None:
    message_id = "wamid-integration-001"
    response = client.post("/webhooks/whatsapp", json=_valid_text_payload(message_id))

    assert response.status_code == 200
    assert _event_count_by_message_id(message_id) == 1


def test_post_webhook_duplicate_payload_returns_200_and_no_duplicate(client: TestClient) -> None:
    message_id = "wamid-integration-duplicate"
    payload = _valid_text_payload(message_id)

    first = client.post("/webhooks/whatsapp", json=payload)
    second = client.post("/webhooks/whatsapp", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _event_count_by_message_id(message_id) == 1


def test_post_webhook_invalid_payload_returns_200_without_crashing(client: TestClient) -> None:
    response = client.post("/webhooks/whatsapp", json={"event": "invalid"})

    assert response.status_code == 200
    assert _total_event_count() == 0
