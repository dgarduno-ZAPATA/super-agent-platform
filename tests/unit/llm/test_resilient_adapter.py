from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from adapters.llm.resilient_adapter import ResilientLLMAdapter
from core.domain.llm import LLMResponse


@pytest.mark.asyncio
async def test_resilient_llm_uses_fallback_when_primary_fails() -> None:
    primary = AsyncMock()
    primary.complete.side_effect = RuntimeError("Vertex down")
    fallback = AsyncMock()
    fallback.complete.return_value = LLMResponse(content="Respuesta de fallback", finish_reason="stop")

    adapter = ResilientLLMAdapter(primary=primary, fallback=fallback)
    result = await adapter.complete(
        system="system",
        messages=[],
        tools=None,
        temperature=0.2,
    )

    assert result.content == "Respuesta de fallback"
    primary.complete.assert_awaited_once()
    fallback.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_resilient_llm_raises_when_both_fail() -> None:
    primary = AsyncMock()
    primary.complete.side_effect = RuntimeError("Vertex down")
    fallback = AsyncMock()
    fallback.complete.side_effect = RuntimeError("OpenAI down")

    adapter = ResilientLLMAdapter(primary=primary, fallback=fallback)

    with pytest.raises(RuntimeError, match="OpenAI down"):
        await adapter.complete(
            system="system",
            messages=[],
            tools=None,
            temperature=0.2,
        )


@pytest.mark.asyncio
async def test_resilient_llm_timeout_triggers_fallback() -> None:
    async def slow_primary(*args, **kwargs) -> LLMResponse:
        del args, kwargs
        await asyncio.sleep(20)
        return LLMResponse(content="nunca llega", finish_reason="stop")

    primary = AsyncMock()
    primary.complete.side_effect = slow_primary
    fallback = AsyncMock()
    fallback.complete.return_value = LLMResponse(content="Respuesta rapida", finish_reason="stop")

    adapter = ResilientLLMAdapter(primary=primary, fallback=fallback, timeout_seconds=0.05)
    result = await adapter.complete(
        system="system",
        messages=[],
        tools=None,
        temperature=0.2,
    )

    assert result.content == "Respuesta rapida"
    primary.complete.assert_awaited_once()
    fallback.complete.assert_awaited_once()
