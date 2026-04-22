from __future__ import annotations

import json

import httpx
import pytest

from adapters.messaging.evolution.adapter import EvolutionMessagingAdapter
from core.config import Settings


@pytest.mark.asyncio
async def test_send_text_normalizes_number_for_evolution_v2() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            status_code=201,
            json={"key": {"id": "msg-001"}},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        base_url="https://evo.example.com",
        headers={"apikey": "test-api-key", "Content-Type": "application/json"},
        transport=transport,
    )
    settings = Settings(
        EVOLUTION_BASE_URL="https://evo.example.com",
        EVOLUTION_API_KEY="test-api-key",
        EVOLUTION_INSTANCE_NAME="Raul Rodriguez",
    )
    adapter = EvolutionMessagingAdapter(settings=settings, client=client)

    try:
        await adapter.send_text(
            to="+52 1 442 123 4567@s.whatsapp.net",
            text="Hola",
            correlation_id="corr-001",
        )
    finally:
        await client.aclose()

    assert captured["path"] == "/message/sendText/Raul Rodriguez"
    assert captured["payload"] == {
        "number": "5214421234567",
        "text": "Hola",
    }
