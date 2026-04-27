from __future__ import annotations

import base64

import pytest

from adapters.llm.vertex_transcription_adapter import VertexTranscriptionAdapter


class FakeVertexAdapter:
    def __init__(self, response_text: str = "Hola, busco camion") -> None:
        self.response_text = response_text
        self.calls: list[list[dict[str, object]]] = []

    async def generate_multimodal(self, parts: list[dict[str, object]]) -> str:
        self.calls.append(parts)
        return self.response_text


def _make_b64(size_bytes: int = 200) -> str:
    return base64.b64encode(b"\x00" * size_bytes).decode("utf-8")


@pytest.mark.asyncio
async def test_transcription_sends_base64_directly_to_gemini() -> None:
    fake_vertex = FakeVertexAdapter("Hola, busco camion")
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]
    audio_b64 = _make_b64(200)

    result = await adapter.transcribe(audio_base64=audio_b64, mime_type="audio/ogg")

    assert result == "Hola, busco camion"
    assert len(fake_vertex.calls) == 1
    inline = fake_vertex.calls[0][0]["inline_data"]
    assert inline["mime_type"] == "audio/ogg"
    assert inline["data"] == audio_b64


@pytest.mark.asyncio
async def test_transcription_strips_mime_type_codec_params() -> None:
    fake_vertex = FakeVertexAdapter("texto")
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]

    result = await adapter.transcribe(
        audio_base64=_make_b64(200), mime_type="audio/ogg; codecs=opus"
    )

    assert result == "texto"
    inline = fake_vertex.calls[0][0]["inline_data"]
    assert inline["mime_type"] == "audio/ogg"


@pytest.mark.asyncio
async def test_transcription_returns_none_for_invalid_base64() -> None:
    fake_vertex = FakeVertexAdapter()
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]

    result = await adapter.transcribe(audio_base64="not-valid!!!", mime_type="audio/ogg")

    assert result is None
    assert len(fake_vertex.calls) == 0


@pytest.mark.asyncio
async def test_transcription_returns_none_for_too_small_audio() -> None:
    fake_vertex = FakeVertexAdapter()
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]

    result = await adapter.transcribe(audio_base64=_make_b64(50), mime_type="audio/ogg")

    assert result is None
    assert len(fake_vertex.calls) == 0


@pytest.mark.asyncio
async def test_transcription_returns_none_when_gemini_returns_empty() -> None:
    fake_vertex = FakeVertexAdapter("")
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]

    result = await adapter.transcribe(audio_base64=_make_b64(200))

    assert result is None
