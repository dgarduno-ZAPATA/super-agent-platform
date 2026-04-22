from __future__ import annotations

import base64

import httpx
import structlog

from adapters.llm.vertex_adapter import VertexLLMAdapter
from core.ports.transcription_provider import TranscriptionProvider

logger = structlog.get_logger("super_agent_platform.adapters.llm.vertex_transcription_adapter")


class VertexTranscriptionAdapter(TranscriptionProvider):
    SUPPORTED_MIME_TYPES = {
        ".ogg": "audio/ogg",
        ".mp4": "audio/mp4",
        ".mpeg": "audio/mpeg",
        ".mp3": "audio/mpeg",
        ".opus": "audio/opus",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
    }
    MAX_AUDIO_BYTES = 10 * 1024 * 1024

    def __init__(self, vertex_adapter: VertexLLMAdapter) -> None:
        self._vertex = vertex_adapter

    async def transcribe(self, audio_url: str, mime_type: str | None = None) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(audio_url)
                response.raise_for_status()
                audio_bytes = response.content

            if len(audio_bytes) > self.MAX_AUDIO_BYTES:
                logger.warning(
                    "audio_transcription_file_too_large",
                    audio_url=audio_url,
                    size_bytes=len(audio_bytes),
                )
                return None

            resolved_mime = self._resolve_mime_type(audio_url=audio_url, mime_type=mime_type)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            result = await self._vertex.generate_multimodal(
                [
                    {"inline_data": {"mime_type": resolved_mime, "data": audio_b64}},
                    {
                        "text": (
                            "Transcribe exactamente lo que dice este audio en espanol. "
                            "Solo devuelve el texto transcrito, sin explicaciones, "
                            "sin prefijos como 'El audio dice:', sin comillas. "
                            "Si no hay voz clara, devuelve exactamente: [INAUDIBLE]"
                        )
                    },
                ]
            )
            cleaned = result.strip()
            if cleaned and cleaned != "[INAUDIBLE]":
                return cleaned
            return None
        except Exception:
            logger.warning("audio_transcription_failed", audio_url=audio_url, exc_info=True)
            return None

    def _resolve_mime_type(self, audio_url: str, mime_type: str | None) -> str:
        if isinstance(mime_type, str) and mime_type.strip():
            return mime_type.strip()
        normalized_url = audio_url.lower().split("?", 1)[0]
        for suffix, resolved in self.SUPPORTED_MIME_TYPES.items():
            if normalized_url.endswith(suffix):
                return resolved
        return "audio/ogg"
