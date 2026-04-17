from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from core.brand.loader import load_brand
from core.domain.messaging import InboundEvent, MessageKind
from core.domain.session import Session
from core.services.orchestrator import OrchestratorAgent


class FakeSilencedUserRepository:
    async def is_silenced(self, phone: str) -> bool:
        del phone
        return False

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        del phone
        del reason
        del silenced_by

    async def unsilence(self, phone: str) -> None:
        del phone


def _build_event(text: str | None, kind: MessageKind = MessageKind.TEXT) -> InboundEvent:
    now = datetime.now(UTC)
    return InboundEvent(
        message_id="wamid-orchestrator",
        from_phone="5214421234567",
        kind=kind,
        text=text,
        media_url=None,
        raw_metadata={},
        received_at=now,
        sender_id="5214421234567@s.whatsapp.net",
        channel="whatsapp",
        event_type="inbound_message",
        occurred_at=now,
        metadata={},
    )


def _build_session(state: str = "greeting", campaign_id: str | None = None) -> Session:
    now = datetime.now(UTC)
    context: dict[str, object] = {}
    if campaign_id is not None:
        context["campaign_id"] = campaign_id
    return Session(
        id=uuid4(),
        lead_id=uuid4(),
        current_state=state,
        context=context,
        created_at=now,
        updated_at=now,
        last_event_at=now,
    )


@pytest.mark.asyncio
async def test_stop_message_is_classified_as_opt_out() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(_build_event("STOP"), _build_session())

    assert result.intent == "opt_out"


@pytest.mark.asyncio
async def test_baja_message_case_insensitive_is_opt_out() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(_build_event("BaJa por favor"), _build_session())

    assert result.intent == "opt_out"


@pytest.mark.asyncio
async def test_message_with_asesor_is_handoff_request() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(
        _build_event("quiero hablar con un asesor"), _build_session()
    )

    assert result.intent == "handoff_request"


@pytest.mark.asyncio
async def test_message_with_humano_is_handoff_request() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(_build_event("humano"), _build_session())

    assert result.intent == "handoff_request"


@pytest.mark.asyncio
async def test_normal_message_is_conversation() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(_build_event("hola quiero un camion"), _build_session())

    assert result.intent == "conversation"


@pytest.mark.asyncio
async def test_unsupported_message_is_classified_as_unsupported() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(
        _build_event(text=None, kind=MessageKind.UNSUPPORTED), _build_session()
    )

    assert result.intent == "unsupported"


@pytest.mark.asyncio
async def test_negative_message_without_opt_out_keyword_is_conversation() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(_build_event("no me interesa"), _build_session())

    assert result.intent == "conversation"


@pytest.mark.asyncio
async def test_stop_keyword_inside_phrase_is_opt_out() -> None:
    brand = load_brand(Path("brand"))
    orchestrator = OrchestratorAgent(brand, brand.fsm, FakeSilencedUserRepository())

    result = await orchestrator.classify(_build_event("stop aqui"), _build_session())

    assert result.intent == "opt_out"
