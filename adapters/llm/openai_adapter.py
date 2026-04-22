from __future__ import annotations

from openai import AsyncOpenAI

from core.domain.llm import LLMResponse, ToolSchema
from core.domain.messaging import ChatMessage
from core.ports.llm_provider import LLMProvider


class OpenAILLMAdapter(LLMProvider):
    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini") -> None:
        self._api_key = api_key.strip()
        self._model_name = model_name
        self._client = AsyncOpenAI(api_key=self._api_key or "missing-key")

    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        del tools

        if not self._api_key:
            raise RuntimeError("OpenAI fallback is not configured (OPENAI_API_KEY is empty)")

        completion = await self._client.chat.completions.create(
            model=self._model_name,
            messages=self._map_messages(messages=messages, system=system),
            max_tokens=1024,
            temperature=temperature,
        )

        choice = completion.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            content = "Gracias por escribirnos. En breve te apoyamos."

        finish_reason = str(choice.finish_reason or "stop")
        return LLMResponse(
            content=content,
            finish_reason=finish_reason,
            metadata={"model": self._model_name, "provider": "openai"},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise NotImplementedError("OpenAI embeddings are not implemented for fallback adapter")

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes
        del mime_type
        raise NotImplementedError("OpenAI audio transcription is not implemented for fallback")

    @staticmethod
    def _map_messages(messages: list[ChatMessage], system: str) -> list[dict[str, str]]:
        mapped: list[dict[str, str]] = [{"role": "system", "content": system}]
        for message in messages:
            if message.role in {"assistant", "model"}:
                role = "assistant"
            elif message.role == "tool":
                role = "user"
            else:
                role = "user"

            content = message.content
            if message.role == "tool":
                tool_name = message.name or "tool"
                content = f"[tool:{tool_name}] {message.content}"

            mapped.append({"role": role, "content": content})
        return mapped
