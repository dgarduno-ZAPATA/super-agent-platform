from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from core.brand.loader import load_brand
from core.domain.messaging import InboundEvent, MessageDeliveryReceipt, MessageKind
from core.domain.session import Session
from core.services.responder import EchoResponder


class FakeMessagingProvider:
    def __init__(self, fail_on_send: bool = False) -> None:
        self.fail_on_send = fail_on_send
        self.sent_messages: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        if self.fail_on_send:
            raise RuntimeError("network down")

        self.sent_messages.append(
            {
                "to": to,
                "text": text,
                "correlation_id": correlation_id,
            }
        )
        return MessageDeliveryReceipt(
            message_id="out-001",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        raise NotImplementedError

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        raise NotImplementedError

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        raise NotImplementedError

    def parse_inbound_event(self, raw_payload: dict[str, object]) -> InboundEvent:
        raise NotImplementedError


def _event(
    kind: MessageKind,
    text: str | None = None,
    metadata: dict[str, object] | None = None,
) -> InboundEvent:
    return InboundEvent(
        message_id="wamid-123",
        from_phone="5214421234567",
        kind=kind,
        text=text,
        media_url=None,
        raw_metadata={},
        received_at=datetime.now(UTC),
        sender_id="5214421234567@s.whatsapp.net",
        channel="whatsapp",
        event_type="inbound_message",
        occurred_at=datetime.now(UTC),
        metadata=metadata or {},
    )


def _session() -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        lead_id=uuid4(),
        current_state="new_lead",
        context={},
        created_at=now,
        updated_at=now,
        last_event_at=now,
    )


@pytest.mark.asyncio
async def test_text_message_responds_with_prefixed_echo() -> None:
    brand = load_brand(Path("brand"))
    provider = FakeMessagingProvider()
    responder = EchoResponder(messaging_provider=provider, brand=brand)

    await responder.respond(_event(MessageKind.TEXT, text="Hola mundo"), _session())

    assert provider.sent_messages[0]["text"] == f"{brand.brand.display_name}: Hola mundo"
    assert provider.sent_messages[0]["correlation_id"] == "wamid-123"


@pytest.mark.asyncio
async def test_audio_message_responds_with_prefixed_transcription() -> None:
    brand = load_brand(Path("brand"))
    provider = FakeMessagingProvider()
    responder = EchoResponder(messaging_provider=provider, brand=brand)
    event = _event(
        MessageKind.AUDIO,
        metadata={"transcription_text": "Necesito cotizacion de un Cascadia"},
    )

    await responder.respond(event, _session())

    assert provider.sent_messages[0]["text"] == (
        f"{brand.brand.display_name} (transcripción): Necesito cotizacion de un Cascadia"
    )


@pytest.mark.asyncio
async def test_unsupported_message_responds_with_generic_text() -> None:
    brand = load_brand(Path("brand"))
    provider = FakeMessagingProvider()
    responder = EchoResponder(messaging_provider=provider, brand=brand)

    await responder.respond(_event(MessageKind.UNSUPPORTED), _session())

    assert provider.sent_messages[0]["text"] == (
        f"{brand.brand.display_name}: Recibí tu mensaje pero no puedo procesar ese tipo de "
        "contenido todavía."
    )


@pytest.mark.asyncio
async def test_send_failure_does_not_crash_and_logs_error() -> None:
    brand = load_brand(Path("brand"))
    provider = FakeMessagingProvider(fail_on_send=True)
    responder = EchoResponder(messaging_provider=provider, brand=brand)

    with patch("core.services.responder.logger.exception") as exception_logger:
        await responder.respond(_event(MessageKind.TEXT, text="Hola"), _session())

    exception_logger.assert_called_once()
