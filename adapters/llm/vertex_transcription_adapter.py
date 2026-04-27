from __future__ import annotations

import base64

import structlog

from adapters.llm.vertex_adapter import VertexLLMAdapter
from core.ports.transcription_provider import TranscriptionProvider

logger = structlog.get_logger("super_agent_platform.adapters.llm.vertex_transcription_adapter")


class VertexTranscriptionAdapter(TranscriptionProvider):
    def __init__(self, vertex_adapter: VertexLLMAdapter) -> None:
        self._vertex = vertex_adapter

    async def transcribe(
        self,
        audio_base64: str,
        mime_type: str = "audio/ogg",
    ) -> str | None:
        mime_type = mime_type.split(";")[0].strip()

        try:
            audio_bytes = base64.b64decode(audio_base64)
        except Exception as exc:
            logger.warning("audio_transcription_invalid_base64", error=str(exc))
            return None

        if len(audio_bytes) < 100:
            logger.warning("audio_transcription_skipped_too_small", size=len(audio_bytes))
            return None

        logger.info("audio_transcription_attempted", mime_type=mime_type, size=len(audio_bytes))

        multimodal_parts: list[dict[str, object]] = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(audio_bytes).decode("utf-8"),
                }
            },
            {
                "text": (
                    "Transcribe este mensaje de voz en español. "
                    "Solo devuelve la transcripción exacta de lo que dice "
                    "la persona, sin agregar nada más. "
                    "Si no se entiende algo, escribe [inaudible]."
                )
            },
        ]

        result = await self._vertex.generate_multimodal(multimodal_parts)

        if not result:
            logger.warning("audio_transcription_empty_result")
            return None

        logger.info("audio_transcription_succeeded", chars=len(result))
        return result
