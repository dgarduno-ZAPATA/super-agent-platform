from __future__ import annotations

import base64
import binascii

import httpx
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class WhatsAppDecryptionError(Exception):
    """Raised when WhatsApp encrypted media cannot be downloaded or decrypted."""

    def __init__(self, message: str, original_exc: Exception | None = None) -> None:
        super().__init__(message)
        self.original_exc = original_exc


async def download_and_decrypt_audio(
    encrypted_url: str,
    media_key_b64: str,
    mime_type: str = "audio/ogg",
) -> bytes:
    """
    Descarga y descifra audio de WhatsApp.
    Devuelve los bytes del audio descifrado listo para Gemini.
    Lanza WhatsAppDecryptionError si algo falla.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(encrypted_url)
            response.raise_for_status()
            encrypted_bytes = response.content
    except Exception as exc:
        raise WhatsAppDecryptionError("failed_to_download_encrypted_media", exc) from exc

    try:
        media_key = base64.b64decode(media_key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WhatsAppDecryptionError("invalid_media_key_base64", exc) from exc

    if len(media_key) == 0:
        raise WhatsAppDecryptionError("empty_media_key")
    if len(encrypted_bytes) <= 10:
        raise WhatsAppDecryptionError("encrypted_media_too_small")

    try:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=112,
            salt=b"\x00" * 32,
            info=b"WhatsApp Audio Keys",
        )
        key_material = hkdf.derive(media_key)
        iv = key_material[16:32]
        cipher_key = key_material[32:64]

        cipher = Cipher(algorithms.AES(cipher_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted_padded = decryptor.update(encrypted_bytes[10:]) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
    except Exception as exc:
        raise WhatsAppDecryptionError(
            f"failed_to_decrypt_whatsapp_audio mime_type={mime_type}",
            exc,
        ) from exc

    if not decrypted:
        raise WhatsAppDecryptionError("decrypted_audio_empty")

    return decrypted
