from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.domain.messaging import MessageDeliveryReceipt
from core.domain.outbound_queue import OutboundQueueItem
from core.services.campaign_worker import CampaignWorker


class FakeOutboundQueueRepository:
    def __init__(self, items: list[OutboundQueueItem]) -> None:
        self.items = items
        self.batch_limit: int | None = None
        self.sent: list[UUID] = []
        self.failed: list[tuple[UUID, str]] = []

    async def get_next_batch(self, limit: int = 10) -> list[OutboundQueueItem]:
        self.batch_limit = limit
        return self.items

    async def mark_as_sent(self, item_id: UUID) -> None:
        self.sent.append(item_id)

    async def mark_as_failed(self, item_id: UUID, error: str) -> None:
        self.failed.append((item_id, error))


class FakeMessagingProvider:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.calls: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        self.calls.append({"to": to, "text": text, "correlation_id": correlation_id})
        if to in self.fail_for:
            raise RuntimeError("provider_error")
        return MessageDeliveryReceipt(
            message_id="wamid-out",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to, image_url, caption, correlation_id
        raise NotImplementedError

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to, document_url, filename, correlation_id
        raise NotImplementedError

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to, audio_url, correlation_id
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        del message_id
        raise NotImplementedError

    @staticmethod
    def parse_inbound_event(raw_payload: dict[str, object]):
        del raw_payload
        raise NotImplementedError


def _item(
    *,
    phone: str | None = "5214421234567",
    payload: dict[str, object] | None = None,
) -> OutboundQueueItem:
    now = datetime.now(UTC)
    base_payload: dict[str, object] = payload or {"text": "Hola demo"}
    return OutboundQueueItem(
        id=uuid4(),
        lead_id=uuid4(),
        lead_phone=phone,
        campaign_id=None,
        priority=1,
        payload=base_payload,
        status="processing",
        scheduled_at=now,
        sent_at=None,
        attempts=1,
        last_error=None,
    )


@pytest.mark.asyncio
async def test_run_once_calls_send_text_for_each_item() -> None:
    items = [_item(), _item(phone="5214420000001")]
    repo = FakeOutboundQueueRepository(items)
    messaging = FakeMessagingProvider()
    worker = CampaignWorker(repo, messaging, batch_size=10, rate_limit_ms=0)

    await worker.run_once()

    assert len(messaging.calls) == 2


@pytest.mark.asyncio
async def test_run_once_marks_done_on_success() -> None:
    item = _item()
    repo = FakeOutboundQueueRepository([item])
    worker = CampaignWorker(repo, FakeMessagingProvider(), batch_size=10, rate_limit_ms=0)

    await worker.run_once()

    assert repo.sent == [item.id]
    assert repo.failed == []


@pytest.mark.asyncio
async def test_run_once_marks_failed_on_messaging_error() -> None:
    item = _item(phone="5214429999999")
    repo = FakeOutboundQueueRepository([item])
    messaging = FakeMessagingProvider(fail_for={"5214429999999"})
    worker = CampaignWorker(repo, messaging, batch_size=10, rate_limit_ms=0)

    await worker.run_once()

    assert repo.sent == []
    assert len(repo.failed) == 1
    assert repo.failed[0][0] == item.id


def test_template_renders_variables_correctly() -> None:
    payload = {
        "template": "Hola {name}, tu cita es {fecha}",
        "variables": {"name": "Juan", "fecha": "lunes"},
    }

    rendered = CampaignWorker._render_message(payload)

    assert rendered == "Hola Juan, tu cita es lunes"


@pytest.mark.asyncio
async def test_run_once_returns_correct_counts() -> None:
    success_item = _item()
    fail_item = _item(phone=None, payload={"text": "Sin telefono"})
    repo = FakeOutboundQueueRepository([success_item, fail_item])
    worker = CampaignWorker(repo, FakeMessagingProvider(), batch_size=10, rate_limit_ms=0)

    result = await worker.run_once()

    assert result.processed == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.duration_ms >= 0
