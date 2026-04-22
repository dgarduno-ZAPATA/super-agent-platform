from __future__ import annotations

import base64

import httpx
import structlog

from adapters.llm.vertex_adapter import VertexLLMAdapter

logger = structlog.get_logger("super_agent_platform.core.services.image_analysis_service")


class ImageAnalysisService:
    SUPPORTED_MIME_TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
    }
    MAX_IMAGE_BYTES = 5 * 1024 * 1024
    PROMPT = (
        "Eres un asesor comercial de camiones y tractocamiones seminuevos. "
        "Describe en maximo 2 oraciones lo que ves en esta imagen, "
        "enfocandote en si es un vehiculo comercial (tipo, marca visible, "
        "estado aparente) o en que es si no lo es. "
        "Se directo y conciso."
    )

    def __init__(self, vertex_adapter: VertexLLMAdapter) -> None:
        self._vertex = vertex_adapter

    async def analyze(self, image_url: str, mime_type: str | None = None) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(image_url)
                response.raise_for_status()
                image_bytes = response.content

            if len(image_bytes) > self.MAX_IMAGE_BYTES:
                logger.warning(
                    "image_analysis_file_too_large",
                    image_url=image_url,
                    size_bytes=len(image_bytes),
                )
                return None

            resolved_mime = self._resolve_mime_type(image_url=image_url, mime_type=mime_type)
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            result = await self._vertex.generate_multimodal(
                [
                    {"inline_data": {"mime_type": resolved_mime, "data": image_b64}},
                    {"text": self.PROMPT},
                ]
            )
            cleaned = result.strip()
            return cleaned if cleaned else None
        except Exception:
            logger.warning("image_analysis_failed", image_url=image_url, exc_info=True)
            return None

    def _resolve_mime_type(self, image_url: str, mime_type: str | None) -> str:
        if isinstance(mime_type, str) and mime_type.strip():
            return mime_type.strip()
        normalized_url = image_url.lower().split("?", 1)[0]
        for suffix, resolved in self.SUPPORTED_MIME_TYPES.items():
            if normalized_url.endswith(suffix):
                return resolved
        return "image/jpeg"
