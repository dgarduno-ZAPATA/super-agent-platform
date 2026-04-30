from __future__ import annotations

from datetime import UTC, datetime

from core.domain.messaging import InboundEvent, MessageKind


def test_inbound_event_has_from_me_field() -> None:
    event = InboundEvent(
        message_id="test-id",
        from_phone="5214461051272",
        kind=MessageKind.TEXT,
        received_at=datetime.now(UTC),
        from_me=True,
    )
    assert event.from_me is True


def test_inbound_event_from_me_defaults_false() -> None:
    event = InboundEvent(
        message_id="test-id",
        from_phone="5214461051272",
        kind=MessageKind.TEXT,
        received_at=datetime.now(UTC),
    )
    assert event.from_me is False
