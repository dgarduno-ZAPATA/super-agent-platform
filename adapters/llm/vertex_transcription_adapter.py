from __future__ import annotations

import base64
import binascii
import hashlib

import httpx
import structlog

from adapters.llm.vertex_adapter import VertexLLMAdapter
from adapters.media.whatsapp_media_decryptor import (
    WhatsAppDecryptionError,
    download_and_decrypt_audio,
)
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

    async def transcribe(
        self,
        audio_url: str,
        mime_type: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str | None:
        try:
            metadata = metadata or {}
            resolved_mime = self._resolve_mime_type(audio_url=audio_url, mime_type=mime_type)
            audio_bytes: bytes
            media_key_value = metadata.get("media_key")
            media_key = media_key_value.strip() if isinstance(media_key_value, str) else ""

            if media_key:
                logger.info(
                    "audio_decryption_attempted",
                    audio_url=audio_url,
                    mime_type=resolved_mime,
                )
                try:
                    audio_bytes = await download_and_decrypt_audio(
                        encrypted_url=audio_url,
                        media_key_b64=media_key,
                        mime_type=resolved_mime,
                    )
                    expected_file_sha = metadata.get("file_sha256")
                    if (
                        isinstance(expected_file_sha, str)
                        and expected_file_sha.strip()
                        and not self._is_matching_sha256(
                            payload=audio_bytes,
                            expected_hash_b64=expected_file_sha,
                        )
                    ):
                        raise WhatsAppDecryptionError("decrypted_file_sha256_mismatch")
                    logger.info(
                        "audio_decryption_succeeded",
                        audio_url=audio_url,
                        mime_type=resolved_mime,
                        size_bytes=len(audio_bytes),
                    )
                except WhatsAppDecryptionError:
                    logger.warning(
                        "audio_decryption_failed",
                        audio_url=audio_url,
                        mime_type=resolved_mime,
                        exc_info=True,
                    )
                    audio_bytes = await self._download_audio(audio_url)
            else:
                audio_bytes = await self._download_audio(audio_url)

            if len(audio_bytes) > self.MAX_AUDIO_BYTES:
                logger.warning(
                    "audio_transcription_file_too_large",
                    audio_url=audio_url,
                    size_bytes=len(audio_bytes),
                )
                return None

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

    @staticmethod
    async def _download_audio(audio_url: str) -> bytes:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(audio_url)
            response.raise_for_status()
            return response.content

    @staticmethod
    def _is_matching_sha256(payload: bytes, expected_hash_b64: str) -> bool:
        try:
            expected = base64.b64decode(expected_hash_b64, validate=True)
        except (binascii.Error, ValueError):
            return False
        return hashlib.sha256(payload).digest() == expected

    def _resolve_mime_type(self, audio_url: str, mime_type: str | None) -> str:
        if isinstance(mime_type, str) and mime_type.strip():
            return mime_type.strip()
        normalized_url = audio_url.lower().split("?", 1)[0]
        for suffix, resolved in self.SUPPORTED_MIME_TYPES.items():
            if normalized_url.endswith(suffix):
                return resolved
        return "audio/ogg"
