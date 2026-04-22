from typing import Protocol


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio_url: str, mime_type: str | None = None) -> str | None:
        """Transcribe an audio URL and return plain text when available."""
