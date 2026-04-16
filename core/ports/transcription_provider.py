from typing import Protocol


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        """Transcribe the provided audio bytes and return plain text."""
