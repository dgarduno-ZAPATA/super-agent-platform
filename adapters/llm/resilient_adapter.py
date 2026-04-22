from __future__ import annotations

import asyncio

import sentry_sdk
import structlog

from core.domain.llm import LLMResponse, ToolSchema
from core.domain.messaging import ChatMessage
from core.ports.llm_provider import LLMProvider

logger = structlog.get_logger("super_agent_platform.adapters.llm.resilient_adapter")


class ResilientLLMAdapter(LLMProvider):
    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._timeout_seconds = timeout_seconds

    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        try:
            return await asyncio.wait_for(
                self._primary.complete(
                    messages=messages,
                    system=system,
                    tools=tools,
                    temperature=temperature,
                ),
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.warning("llm_primary_failed_using_fallback", error=str(exc))
            try:
                return await asyncio.wait_for(
                    self._fallback.complete(
                        messages=messages,
                        system=system,
                        tools=tools,
                        temperature=temperature,
                    ),
                    timeout=self._timeout_seconds,
                )
            except Exception as fallback_exc:
                sentry_sdk.capture_exception(fallback_exc)
                logger.error("llm_fallback_also_failed", error=str(fallback_exc))
                raise

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._primary.embed(texts)

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        return await self._primary.transcribe_audio(audio_bytes, mime_type)
