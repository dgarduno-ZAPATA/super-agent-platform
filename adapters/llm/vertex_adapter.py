from __future__ import annotations

import os
from typing import Any

import httpx

from core.domain.llm import LLMResponse, ToolCall, ToolSchema
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
        embedding_model_name: str = "text-embedding-004",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._project_id = project_id
        self._region = region
        self._model_name = model_name
        self._embedding_model_name = embedding_model_name
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
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
        if tools:
            payload["tools"] = [
                {"functionDeclarations": [self._map_tool_schema(tool) for tool in tools]}
            ]

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
        parsed_tool_calls: list[ToolCall] = []

        if isinstance(parts, list):
            for index, part in enumerate(parts):
                if not isinstance(part, dict):
                    continue

                text_value = part.get("text")
                if isinstance(text_value, str):
                    text_chunks.append(text_value)

                function_call_raw = part.get("functionCall")
                if not isinstance(function_call_raw, dict):
                    continue

                name = function_call_raw.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue

                args_raw = function_call_raw.get("args")
                arguments = args_raw if isinstance(args_raw, dict) else {}

                call_id_raw = function_call_raw.get("id")
                call_id = (
                    call_id_raw
                    if isinstance(call_id_raw, str) and call_id_raw.strip()
                    else f"tool_call_{index}"
                )
                parsed_tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=name,
                        arguments=arguments,
                    )
                )

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
            tool_calls=tuple(parsed_tool_calls),
            metadata={"model": self._model_name, "provider": "vertex"},
        )

    async def generate_multimodal(self, parts: list[dict[str, object]]) -> str:
        access_token = await self._resolve_access_token()
        endpoint = (
            f"https://{self._region}-aiplatform.googleapis.com/v1/projects/"
            f"{self._project_id}/locations/{self._region}/publishers/google/models/"
            f"{self._model_name}:generateContent"
        )
        normalized_parts = [self._normalize_multimodal_part(part) for part in parts]
        payload: dict[str, object] = {
            "contents": [{"role": "user", "parts": normalized_parts}],
            "generationConfig": {"temperature": 0.2},
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
            raise RuntimeError("vertex multimodal response missing candidates")

        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise RuntimeError("vertex multimodal response candidate format is invalid")

        content = first_candidate.get("content", {})
        response_parts = content.get("parts", []) if isinstance(content, dict) else []
        text_chunks: list[str] = []
        if isinstance(response_parts, list):
            for part in response_parts:
                if not isinstance(part, dict):
                    continue
                text_value = part.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    text_chunks.append(text_value.strip())

        response_text = "\n".join(text_chunks).strip()
        if not response_text:
            raise RuntimeError("vertex multimodal response missing text content")
        return response_text

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        access_token = await self._resolve_access_token()
        endpoint = (
            f"https://{self._region}-aiplatform.googleapis.com/v1/projects/"
            f"{self._project_id}/locations/{self._region}/publishers/google/models/"
            f"{self._embedding_model_name}:predict"
        )
        payload: dict[str, object] = {
            "instances": [{"content": text} for text in texts],
            "parameters": {"outputDimensionality": 768},
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
        predictions = body.get("predictions")
        if not isinstance(predictions, list):
            raise RuntimeError("vertex embeddings response missing predictions")

        vectors: list[list[float]] = []
        for item in predictions:
            if not isinstance(item, dict):
                raise RuntimeError("vertex embeddings prediction format is invalid")

            raw_values = None
            embeddings = item.get("embeddings")
            if isinstance(embeddings, dict):
                values = embeddings.get("values")
                if isinstance(values, list):
                    raw_values = values
            if raw_values is None:
                values = item.get("values")
                if isinstance(values, list):
                    raw_values = values

            if raw_values is None:
                raise RuntimeError("vertex embeddings prediction missing vector values")

            vector: list[float] = []
            for value in raw_values:
                if isinstance(value, int | float):
                    vector.append(float(value))
                else:
                    raise RuntimeError("vertex embeddings prediction contains non-numeric value")
            vectors.append(vector)

        if len(vectors) != len(texts):
            raise RuntimeError("vertex embeddings response count mismatch")

        return vectors

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
        if message.role == "tool":
            tool_name = message.name or str(message.metadata.get("tool_name") or "")
            response_payload: dict[str, object] = {
                "name": tool_name,
                "response": {"content": message.content},
            }
            if message.tool_call_id:
                response_payload["id"] = message.tool_call_id
            return {"role": "user", "parts": [{"functionResponse": response_payload}]}

        role = "model" if message.role in {"assistant", "model"} else "user"
        parts: list[dict[str, object]] = []
        if message.content:
            parts.append({"text": message.content})

        if role == "model":
            tool_calls_raw = message.metadata.get("tool_calls")
            if isinstance(tool_calls_raw, tuple | list):
                for raw_call in tool_calls_raw:
                    if isinstance(raw_call, ToolCall):
                        name = raw_call.name
                        arguments = raw_call.arguments
                    elif isinstance(raw_call, dict):
                        raw_name = raw_call.get("name")
                        raw_arguments = raw_call.get("arguments")
                        name = raw_name if isinstance(raw_name, str) else ""
                        arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
                    else:
                        continue

                    if not name:
                        continue
                    parts.append({"functionCall": {"name": name, "args": arguments}})

        if not parts:
            parts.append({"text": ""})
        return {"role": role, "parts": parts}

    @staticmethod
    def _map_tool_schema(tool: ToolSchema) -> dict[str, object]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }

    @staticmethod
    def _normalize_multimodal_part(part: dict[str, object]) -> dict[str, object]:
        inline_data = part.get("inline_data")
        if isinstance(inline_data, dict):
            return {"inlineData": inline_data}
        return part
