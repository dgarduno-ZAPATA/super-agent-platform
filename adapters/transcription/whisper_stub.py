import structlog

from core.ports.transcription_provider import TranscriptionProvider

logger = structlog.get_logger("super_agent_platform.adapters.transcription.whisper_stub")


class WhisperStubTranscriptionProvider(TranscriptionProvider):
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        logger.warning(
            "audio_transcription_stub_used",
            audio_size_bytes=len(audio_bytes),
            mime_type=mime_type,
        )
        return "Audio transcription not yet implemented"
