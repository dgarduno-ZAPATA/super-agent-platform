from typing import Protocol

from core.domain.llm import LLMResponse, ToolSchema
from core.domain.messaging import ChatMessage


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        """Generate a canonical assistant response from the given chat context and tool options."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors aligned by index with the provided texts."""

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        """Transcribe audio bytes into plain text using the provided media type hint."""
