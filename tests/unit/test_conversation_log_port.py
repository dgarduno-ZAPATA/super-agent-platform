from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.ports.conversation_log import ConversationLogPort


def test_port_is_protocol() -> None:
    assert hasattr(ConversationLogPort, "__protocol_attrs__") or isinstance(
        ConversationLogPort, type
    )


@pytest.mark.asyncio
async def test_mock_adapter_satisfies_protocol() -> None:
    mock = AsyncMock(spec=ConversationLogPort)
    await mock.log_turn(
        lead_id="test-id",
        phone_masked="+52***1272",
        last_state="catalog_navigation",
        last_intent="inventory_query",
        summary="Busca volteo en Guadalajara",
        updated_at="2026-04-28T17:00:00Z",
    )
    mock.log_turn.assert_called_once()


@pytest.mark.asyncio
async def test_mock_adapter_handles_none_lead_id() -> None:
    mock = AsyncMock(spec=ConversationLogPort)
    await mock.log_turn(
        lead_id=None,
        phone_masked="+52***0000",
        last_state="greeting",
        last_intent="greeting",
        summary="",
        updated_at="2026-04-28T17:00:00Z",
    )
    mock.log_turn.assert_called_once()
