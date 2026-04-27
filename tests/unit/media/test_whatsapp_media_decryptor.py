from __future__ import annotations

import base64
import os

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from adapters.media.whatsapp_media_decryptor import (
    WhatsAppDecryptionError,
    download_and_decrypt_audio,
)


class _FakeClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    async def get(self, url: str) -> httpx.Response:
        del url
        return self._response


def _build_encrypted_audio_payload(plain_audio: bytes, media_key: bytes) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=112,
        salt=b"\x00" * 32,
        info=b"WhatsApp Audio Keys",
    )
    key_material = hkdf.derive(media_key)
    iv = key_material[16:32]
    cipher_key = key_material[32:64]

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plain_audio) + padder.finalize()

    cipher = Cipher(algorithms.AES(cipher_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return (b"\x00" * 10) + encrypted


@pytest.mark.asyncio
async def test_download_and_decrypt_audio_returns_plain_ogg_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain_audio = b"OggS" + os.urandom(52)
    media_key = os.urandom(32)
    encrypted = _build_encrypted_audio_payload(plain_audio=plain_audio, media_key=media_key)
    request = httpx.Request("GET", "https://cdn.example.com/audio.enc")
    response = httpx.Response(status_code=200, content=encrypted, request=request)

    monkeypatch.setattr(
        "adapters.media.whatsapp_media_decryptor.httpx.AsyncClient",
        lambda timeout: _FakeClient(response),  # noqa: ARG005
    )

    decrypted = await download_and_decrypt_audio(
        encrypted_url="https://cdn.example.com/audio.enc",
        media_key_b64=base64.b64encode(media_key).decode("utf-8"),
    )

    assert decrypted == plain_audio
    assert decrypted.startswith(b"OggS")


@pytest.mark.asyncio
async def test_download_and_decrypt_audio_raises_when_download_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "https://cdn.example.com/audio.enc")
    response = httpx.Response(status_code=404, content=b"", request=request)

    monkeypatch.setattr(
        "adapters.media.whatsapp_media_decryptor.httpx.AsyncClient",
        lambda timeout: _FakeClient(response),  # noqa: ARG005
    )

    with pytest.raises(WhatsAppDecryptionError):
        await download_and_decrypt_audio(
            encrypted_url="https://cdn.example.com/audio.enc",
            media_key_b64=base64.b64encode(os.urandom(32)).decode("utf-8"),
        )
