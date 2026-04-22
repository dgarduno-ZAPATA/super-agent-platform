from __future__ import annotations

import anthropic

from core.domain.llm import LLMResponse, ToolSchema
from core.domain.messaging import ChatMessage
from core.ports.llm_provider import LLMProvider


class AnthropicLLMAdapter(LLMProvider):
    def __init__(self, api_key: str, model_name: str = "claude-haiku-4-5-20251001") -> None:
        self._api_key = api_key.strip()
        self._model_name = model_name
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key or "missing-key")

    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        del tools

        if not self._api_key:
            raise RuntimeError("Anthropic fallback is not configured (ANTHROPIC_API_KEY is empty)")

        anthropic_messages = [self._map_message(message) for message in messages]
        response = await self._client.messages.create(
            model=self._model_name,
            max_tokens=1024,
            system=system,
            messages=anthropic_messages,
            temperature=temperature,
        )

        text_parts = [
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ]
        content = "\n".join(part.strip() for part in text_parts if part and part.strip()).strip()
        if not content:
            content = "Gracias por escribirnos. En breve te apoyamos."

        return LLMResponse(
            content=content,
            finish_reason=str(getattr(response, "stop_reason", "stop")),
            metadata={"model": self._model_name, "provider": "anthropic"},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise NotImplementedError("Anthropic embeddings are not implemented for fallback adapter")

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes
        del mime_type
        raise NotImplementedError("Anthropic audio transcription is not implemented for fallback")

    @staticmethod
    def _map_message(message: ChatMessage) -> dict[str, str]:
        if message.role in {"assistant", "model"}:
            return {"role": "assistant", "content": message.content}
        if message.role == "tool":
            tool_name = message.name or "tool"
            return {
                "role": "user",
                "content": f"[tool:{tool_name}] {message.content}",
            }
        return {"role": "user", "content": message.content}
