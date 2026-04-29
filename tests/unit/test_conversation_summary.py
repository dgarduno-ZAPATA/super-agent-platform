from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.conversation_summary import ConversationSummaryService


@pytest.mark.asyncio
async def test_generate_with_history() -> None:
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = SimpleNamespace(
        content=(
            "El lead busca un volteo en Guadalajara. " "Mostro interes en precio y financiamiento."
        )
    )
    svc = ConversationSummaryService(mock_llm)

    summary = await svc.generate(
        conversation_history=[
            {"role": "user", "content": "busco un volteo"},
            {"role": "assistant", "content": "Tenemos opciones"},
        ],
        trigger_event="handoff_requested",
    )

    assert len(summary) > 10
    mock_llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_generate_empty_history_fallback() -> None:
    mock_llm = AsyncMock()
    svc = ConversationSummaryService(mock_llm)

    summary = await svc.generate(
        conversation_history=[],
        trigger_event="handoff_requested",
        lead_name="Diego",
        vehicle_interest="volteo",
    )

    assert "handoff_requested" in summary
    assert "Diego" in summary
    mock_llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_returns_fallback() -> None:
    mock_llm = AsyncMock()
    mock_llm.complete.side_effect = Exception("LLM timeout")
    svc = ConversationSummaryService(mock_llm)

    summary = await svc.generate(
        conversation_history=[{"role": "user", "content": "hola"}],
        trigger_event="friction_escalation",
        vehicle_interest="tractocamion",
    )

    assert "friction_escalation" in summary
    assert "tractocamion" in summary


@pytest.mark.asyncio
async def test_empty_llm_response_returns_fallback() -> None:
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = SimpleNamespace(content="   ")
    svc = ConversationSummaryService(mock_llm)

    summary = await svc.generate(
        conversation_history=[{"role": "user", "content": "hola"}],
        trigger_event="stage_change",
        lead_name="Maria",
    )

    assert "stage_change" in summary
    assert "Maria" in summary


def test_fallback_summary_minimal() -> None:
    summary = ConversationSummaryService._fallback_summary("stage_change", None, None)
    assert "stage_change" in summary


def test_fallback_summary_full() -> None:
    summary = ConversationSummaryService._fallback_summary(
        "handoff_requested",
        "Diego",
        "volteo",
    )
    assert "Diego" in summary
    assert "volteo" in summary
