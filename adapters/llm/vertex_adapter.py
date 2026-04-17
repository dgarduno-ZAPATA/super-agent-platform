from __future__ import annotations

import os
from typing import Any

import httpx

from core.domain.llm import LLMResponse, ToolSchema
from core.domain.messaging import ChatMessage
from core.ports.llm_provider import LLMProvider

_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/" "service-accounts/default/token"
)


class VertexLLMAdapter(LLMProvider):
    def __init__(
        self,
        project_id: str,
        region: str,
        model_name: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._project_id = project_id
        self._region = region
        self._model_name = model_name
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        del tools

        access_token = await self._resolve_access_token()
        endpoint = (
            f"https://{self._region}-aiplatform.googleapis.com/v1/projects/"
            f"{self._project_id}/locations/{self._region}/publishers/google/models/"
            f"{self._model_name}:generateContent"
        )
        payload: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [self._map_message(message) for message in messages],
            "generationConfig": {"temperature": temperature},
        }

        response = await self._client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()

        body = response.json()
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise RuntimeError("vertex completion response missing candidates")

        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise RuntimeError("vertex completion response candidate format is invalid")

        content = first_candidate.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text_chunks: list[str] = []
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict):
                    text_value = part.get("text")
                    if isinstance(text_value, str):
                        text_chunks.append(text_value)

        response_text = "\n".join(chunk for chunk in text_chunks if chunk).strip()
        if not response_text:
            response_text = "Gracias por escribirnos. En breve te apoyamos."

        finish_reason_raw = first_candidate.get("finishReason")
        finish_reason = (
            finish_reason_raw.lower() if isinstance(finish_reason_raw, str) else "unknown"
        )

        return LLMResponse(
            content=response_text,
            finish_reason=finish_reason,
            metadata={"model": self._model_name, "provider": "vertex"},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise NotImplementedError("Vertex embeddings are not implemented yet")

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes
        del mime_type
        raise NotImplementedError("Vertex audio transcription is not implemented yet")

    async def _resolve_access_token(self) -> str:
        env_token = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
        if env_token is not None and env_token.strip():
            return env_token.strip()

        response = await self._client.get(
            _METADATA_TOKEN_URL,
            headers={"Metadata-Flavor": "Google"},
        )
        response.raise_for_status()

        body = response.json()
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("unable to resolve ADC access token from metadata server")

        return token

    @staticmethod
    def _map_message(message: ChatMessage) -> dict[str, Any]:
        role_map = {"assistant": "model"}
        role = role_map.get(message.role, "user")
        return {"role": role, "parts": [{"text": message.content}]}
