from __future__ import annotations

import base64
import hashlib

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
async def test_vertex_transcription_adapter_transcribes_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


@pytest.mark.asyncio
async def test_vertex_transcription_adapter_uses_url_fallback_when_media_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_vertex = FakeVertexAdapter("Transcripcion normal")
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "adapters.llm.vertex_transcription_adapter.httpx.AsyncClient",
        lambda timeout: _FakeAudioClient(b"audio-bytes"),  # noqa: ARG005
    )

    async def _unexpected_decrypt(
        encrypted_url: str,
        media_key_b64: str,
        mime_type: str = "audio/ogg",
    ) -> bytes:
        del encrypted_url, media_key_b64, mime_type
        raise AssertionError("decryptor must not be called when media_key is absent")

    monkeypatch.setattr(
        "adapters.llm.vertex_transcription_adapter.download_and_decrypt_audio",
        _unexpected_decrypt,
    )

    result = await adapter.transcribe(
        "https://cdn.example.com/audio.ogg",
        metadata={},
    )

    assert result == "Transcripcion normal"
    assert len(fake_vertex.calls) == 1


@pytest.mark.asyncio
async def test_vertex_transcription_adapter_uses_decryptor_when_media_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_vertex = FakeVertexAdapter("Texto descifrado")
    adapter = VertexTranscriptionAdapter(vertex_adapter=fake_vertex)  # type: ignore[arg-type]
    decrypted_audio = b"OggS-decrypted-audio"

    async def _fake_decrypt(
        encrypted_url: str,
        media_key_b64: str,
        mime_type: str = "audio/ogg",
    ) -> bytes:
        del encrypted_url, media_key_b64, mime_type
        return decrypted_audio

    class _FailClient:
        async def __aenter__(self) -> _FailClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> httpx.Response:
            del url
            raise AssertionError("URL fallback should not be used when decrypt succeeds")

    monkeypatch.setattr(
        "adapters.llm.vertex_transcription_adapter.download_and_decrypt_audio",
        _fake_decrypt,
    )
    monkeypatch.setattr(
        "adapters.llm.vertex_transcription_adapter.httpx.AsyncClient",
        lambda timeout: _FailClient(),  # noqa: ARG005
    )

    file_sha = base64.b64encode(hashlib.sha256(decrypted_audio).digest()).decode("utf-8")
    result = await adapter.transcribe(
        "https://cdn.example.com/audio.enc",
        mime_type="audio/ogg",
        metadata={"media_key": "bWVkaWEta2V5", "file_sha256": file_sha},
    )

    assert result == "Texto descifrado"
    assert len(fake_vertex.calls) == 1
