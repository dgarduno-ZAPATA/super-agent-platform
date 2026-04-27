import structlog

from core.ports.transcription_provider import TranscriptionProvider

logger = structlog.get_logger("super_agent_platform.adapters.transcription.whisper_stub")


class WhisperStubTranscriptionProvider(TranscriptionProvider):
    async def transcribe(
        self,
        audio_url: str,
        mime_type: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str | None:
        logger.warning(
            "audio_transcription_stub_used",
            audio_url=audio_url,
            mime_type=mime_type,
            has_metadata=bool(metadata),
        )
        return None
