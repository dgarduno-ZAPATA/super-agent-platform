from adapters.messaging.evolution.normalizers import (
    extract_text,
    normalize_message_type,
    normalize_phone,
)
from adapters.messaging.evolution.payloads import EvolutionMessagePayload
from core.domain.messaging import MessageKind


def test_normalize_phone_handles_supported_formats() -> None:
    assert normalize_phone("5214421234567@s.whatsapp.net") == "5214421234567"
    assert normalize_phone("+5214421234567@lid") == "5214421234567"
    assert normalize_phone("521-442-123-4567@s.whatsapp.net") == "5214421234567"


def test_normalize_phone_returns_none_for_group() -> None:
    assert normalize_phone("120363043965000000@g.us") is None


def test_normalize_message_type_maps_known_types() -> None:
    assert normalize_message_type("conversation") is MessageKind.TEXT
    assert normalize_message_type("imageMessage") is MessageKind.IMAGE
    assert normalize_message_type("audioMessage") is MessageKind.AUDIO
    assert normalize_message_type("documentMessage") is MessageKind.DOCUMENT
    assert normalize_message_type("videoMessage") is MessageKind.VIDEO
    assert normalize_message_type("stickerMessage") is MessageKind.UNSUPPORTED
    assert normalize_message_type("unknownType") is MessageKind.UNSUPPORTED


def test_extract_text_reads_supported_subtypes() -> None:
    conversation_payload = EvolutionMessagePayload.model_validate(
        {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "msg-1",
                "fromMe": False,
            },
            "messageType": "conversation",
            "message": {"conversation": "hola"},
            "pushName": "Cliente",
            "messageTimestamp": 1713200000,
        }
    )
    extended_payload = EvolutionMessagePayload.model_validate(
        {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "msg-2",
                "fromMe": False,
            },
            "messageType": "extendedTextMessage",
            "message": {"extendedTextMessage": {"text": "necesito informacion"}},
            "pushName": "Cliente",
            "messageTimestamp": 1713200001,
        }
    )
    image_payload = EvolutionMessagePayload.model_validate(
        {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "msg-3",
                "fromMe": False,
            },
            "messageType": "imageMessage",
            "message": {"imageMessage": {"caption": "te comparto la unidad", "url": "https://cdn"}},
            "pushName": "Cliente",
            "messageTimestamp": 1713200002,
        }
    )

    assert extract_text(conversation_payload) == "hola"
    assert extract_text(extended_payload) == "necesito informacion"
    assert extract_text(image_payload) == "te comparto la unidad"
