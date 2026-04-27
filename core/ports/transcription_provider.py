from typing import Protocol


class TranscriptionProvider(Protocol):
    async def transcribe(
        self,
        audio_base64: str,
        mime_type: str = "audio/ogg",
    ) -> str | None:
        """Transcribe audio supplied as a base64-encoded string and return plain text."""
