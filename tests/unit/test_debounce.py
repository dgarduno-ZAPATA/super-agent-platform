from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from core.domain.messaging import InboundEvent, MessageKind
from core.services.inbound_handler import (
    InboundMessageHandler,
    _debounce_latest,
    _debounce_tasks,
)


def _build_event(message_id: str, phone: str, text: str) -> InboundEvent:
    now = datetime.now(UTC)
    return InboundEvent(
        message_id=message_id,
        from_phone=phone,
        kind=MessageKind.TEXT,
        text=text,
        received_at=now,
        sender_id=f"{phone}@s.whatsapp.net",
    )


def _build_handler(delay_seconds: float = 0.05) -> InboundMessageHandler:
    handler = object.__new__(InboundMessageHandler)
    handler._message_accumulation_seconds = delay_seconds
    return handler


@pytest.fixture(autouse=True)
def _reset_debounce_state() -> None:
    for task in list(_debounce_tasks.values()):
        task.cancel()
    _debounce_tasks.clear()
    _debounce_latest.clear()


@pytest.mark.asyncio
async def test_single_message_fires() -> None:
    handler = _build_handler(0.05)
    event = _build_event("msg-1", "5211111111111", "hola")

    should_process = await handler._handle_with_debounce("5211111111111", event)

    assert should_process is True


@pytest.mark.asyncio
async def test_rapid_messages_fire_once() -> None:
    handler = _build_handler(0.05)
    first = _build_event("msg-1", "5211111111111", "primero")
    second = _build_event("msg-2", "5211111111111", "segundo")
    third = _build_event("msg-3", "5211111111111", "tercero")

    first_task = asyncio.create_task(handler._handle_with_debounce("5211111111111", first))
    await asyncio.sleep(0.01)
    second_task = asyncio.create_task(handler._handle_with_debounce("5211111111111", second))
    await asyncio.sleep(0.01)
    third_task = asyncio.create_task(handler._handle_with_debounce("5211111111111", third))

    results = await asyncio.gather(first_task, second_task, third_task)

    assert results.count(True) == 1
    assert results.count(False) == 2


@pytest.mark.asyncio
async def test_last_message_is_processed() -> None:
    handler = _build_handler(0.05)
    processed: list[str] = []

    async def _send(event: InboundEvent) -> None:
        should_process = await handler._handle_with_debounce(event.from_phone, event)
        if should_process and event.text is not None:
            processed.append(event.text)

    first = _build_event("msg-1", "5211111111111", "primero")
    second = _build_event("msg-2", "5211111111111", "segundo")
    third = _build_event("msg-3", "5211111111111", "tercero")

    first_task = asyncio.create_task(_send(first))
    await asyncio.sleep(0.01)
    second_task = asyncio.create_task(_send(second))
    await asyncio.sleep(0.01)
    third_task = asyncio.create_task(_send(third))

    await asyncio.gather(first_task, second_task, third_task)

    assert processed == ["tercero"]


@pytest.mark.asyncio
async def test_different_jids_independent() -> None:
    handler = _build_handler(0.05)
    processed_a: list[str] = []
    processed_b: list[str] = []

    async def _send(event: InboundEvent, bucket: list[str]) -> None:
        should_process = await handler._handle_with_debounce(event.from_phone, event)
        if should_process and event.text is not None:
            bucket.append(event.text)

    event_a = _build_event("msg-a-1", "5211111111111", "mensaje-a")
    event_b = _build_event("msg-b-1", "5212222222222", "mensaje-b")

    await asyncio.gather(
        asyncio.create_task(_send(event_a, processed_a)),
        asyncio.create_task(_send(event_b, processed_b)),
    )

    assert len(processed_a) == 1
    assert len(processed_b) == 1
