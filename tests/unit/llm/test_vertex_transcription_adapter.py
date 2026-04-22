from __future__ import annotations

import httpx
import pytest

from adapters.llm.vertex_transcription_adapter import VertexTranscriptionAdapter


class FakeVertexAdapter:
    def __init__(self, response_text: str = "Hola, busco camion") -> None:
        self.response_text = response_text
        self.calls: list[list[dict[str, object]]] = []

    async def generate_multimodal(self, parts: list[dict[str, object]]) -> str:
        self.calls.append(parts)
        return self.response_text


class _FakeAudioClient:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aenter__(self) -> _FakeAudioClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    async def get(self, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(status_code=200, content=self._content, request=request)


@pytest.mark.asyncio
async def test_vertex_transcription_adapter_transcribes_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_vertex = FakeVertexAdapter("Hola, busco camion")
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "adapters.llm.vertex_transcription_adapter.httpx.AsyncClient",
        lambda timeout: _FakeAudioClient(b"audio-bytes"),  # noqa: ARG005
    )

    result = await adapter.transcribe("https://cdn.example.com/audio.ogg")

    assert result == "Hola, busco camion"
    assert len(fake_vertex.calls) == 1


@pytest.mark.asyncio
async def test_vertex_transcription_adapter_returns_none_for_inaudible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_vertex = FakeVertexAdapter("[INAUDIBLE]")
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "adapters.llm.vertex_transcription_adapter.httpx.AsyncClient",
        lambda timeout: _FakeAudioClient(b"audio-bytes"),  # noqa: ARG005
    )

    result = await adapter.transcribe("https://cdn.example.com/audio.ogg")

    assert result is None
