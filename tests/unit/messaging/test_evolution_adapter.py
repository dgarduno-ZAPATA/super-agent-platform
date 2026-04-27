from adapters.messaging.evolution.adapter import EvolutionMessagingAdapter
from core.domain.messaging import (
    InvalidInboundPayloadError,
    MessageKind,
)


def _text_payload(remote_jid: str) -> dict[str, object]:
    return {
        "event": "messages.upsert",
        "instance": "selectrucks-zapata",
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "id": "ABGGFlA5FpafAgo6EhQ123456789",
                "fromMe": False,
            },
            "messageType": "conversation",
            "message": {"conversation": "Hola, me interesa un Cascadia 2020"},
            "pushName": "Cliente Demo",
            "messageTimestamp": 1713200000,
            "instanceId": "instance-1",
            "source": "android",
        },
    }


def test_parse_inbound_event_returns_canonical_text_event() -> None:
    event = EvolutionMessagingAdapter.parse_inbound_event(
        _text_payload("5214421234567@s.whatsapp.net")
    )

    assert event.message_id == "ABGGFlA5FpafAgo6EhQ123456789"
    assert event.from_phone == "5214421234567"
    assert event.kind is MessageKind.TEXT
    assert event.text == "Hola, me interesa un Cascadia 2020"
    assert event.media_url is None


def test_parse_inbound_event_normalizes_lid_sender() -> None:
    event = EvolutionMessagingAdapter.parse_inbound_event(_text_payload("+5214421234567@lid"))

    assert event.from_phone == "5214421234567"


def test_parse_inbound_event_maps_sticker_to_unsupported() -> None:
    payload = {
        "event": "messages.upsert",
        "instance": "selectrucks-zapata",
        "data": {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "sticker-msg-1",
                "fromMe": False,
            },
            "messageType": "stickerMessage",
            "message": {"stickerMessage": {"url": "https://cdn.example.com/sticker.webp"}},
            "pushName": "Cliente Demo",
            "messageTimestamp": 1713200001,
            "instanceId": "instance-1",
            "source": "ios",
        },
    }

    event = EvolutionMessagingAdapter.parse_inbound_event(payload)

    assert event.kind is MessageKind.UNSUPPORTED
    assert event.media_url == "https://cdn.example.com/sticker.webp"


def test_parse_inbound_event_rejects_group_message() -> None:
    payload = _text_payload("120363043965000000@g.us")

    try:
        EvolutionMessagingAdapter.parse_inbound_event(payload)
    except InvalidInboundPayloadError as exc:
        assert "group" in str(exc)
    else:
        raise AssertionError("Expected InvalidInboundPayloadError for group message")


def test_parse_inbound_event_normalizes_mexican_phone() -> None:
    event = EvolutionMessagingAdapter.parse_inbound_event(
        _text_payload("+5214421234567@s.whatsapp.net")
    )

    assert event.from_phone == "5214421234567"


def test_parse_inbound_event_handles_audio_message() -> None:
    payload = {
        "event": "messages.upsert",
        "instance": "selectrucks-zapata",
        "data": {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "audio-msg-1",
                "fromMe": False,
            },
            "messageType": "audioMessage",
            "message": {"audioMessage": {"url": "https://cdn.example.com/audio.ogg"}},
            "pushName": "Cliente Demo",
            "messageTimestamp": 1713200002,
            "instanceId": "instance-1",
            "source": "android",
        },
    }

    event = EvolutionMessagingAdapter.parse_inbound_event(payload)

    assert event.kind is MessageKind.AUDIO
    assert event.media_url == "https://cdn.example.com/audio.ogg"
    assert event.text is None
    assert event.metadata["media_key"] is None
    assert event.metadata["file_enc_sha256"] is None
    assert event.metadata["file_sha256"] is None


def test_parse_inbound_event_extracts_audio_crypto_metadata() -> None:
    payload = {
        "event": "messages.upsert",
        "instance": "selectrucks-zapata",
        "data": {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "audio-msg-2",
                "fromMe": False,
            },
            "messageType": "audioMessage",
            "message": {
                "audioMessage": {
                    "url": "https://cdn.example.com/audio.enc",
                    "mediaKey": "bWVkaWEtMTIz",
                    "fileEncSha256": "ZW5jLWhhc2g=",
                    "fileSha256": "ZmlsZS1oYXNo",
                }
            },
            "pushName": "Cliente Demo",
            "messageTimestamp": 1713200002,
            "instanceId": "instance-1",
            "source": "android",
        },
    }

    event = EvolutionMessagingAdapter.parse_inbound_event(payload)

    assert event.kind is MessageKind.AUDIO
    assert event.metadata["media_key"] == "bWVkaWEtMTIz"
    assert event.metadata["file_enc_sha256"] == "ZW5jLWhhc2g="
    assert event.metadata["file_sha256"] == "ZmlsZS1oYXNo"


def test_parse_inbound_event_extracts_audio_crypto_metadata_from_top_level_fallback() -> None:
    payload = {
        "event": "messages.upsert",
        "instance": "selectrucks-zapata",
        "mediaKey": "bWVkaWEtZmFsbGJhY2s=",
        "fileEncSha256": "ZW5jLWZhbGxiYWNr",
        "fileSha256": "ZmlsZS1mYWxsYmFjaw==",
        "data": {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "audio-msg-3",
                "fromMe": False,
            },
            "messageType": "audioMessage",
            "message": {
                "audioMessage": {
                    "url": "https://cdn.example.com/audio.enc",
                }
            },
            "pushName": "Cliente Demo",
            "messageTimestamp": 1713200003,
            "instanceId": "instance-1",
            "source": "android",
        },
    }

    event = EvolutionMessagingAdapter.parse_inbound_event(payload)

    assert event.kind is MessageKind.AUDIO
    assert event.metadata["media_key"] == "bWVkaWEtZmFsbGJhY2s="
    assert event.metadata["file_enc_sha256"] == "ZW5jLWZhbGxiYWNr"
    assert event.metadata["file_sha256"] == "ZmlsZS1mYWxsYmFjaw=="


def test_parse_inbound_event_maps_ptt_message_as_audio() -> None:
    payload = {
        "event": "messages.upsert",
        "instance": "selectrucks-zapata",
        "data": {
            "key": {
                "remoteJid": "5214421234567@s.whatsapp.net",
                "id": "ptt-msg-1",
                "fromMe": False,
            },
            "messageType": "pttMessage",
            "message": {
                "pttMessage": {
                    "url": "https://cdn.example.com/voice.enc",
                    "mediaKey": "cHR0LW1lZGlhLWtleQ==",
                }
            },
            "pushName": "Cliente Demo",
            "messageTimestamp": 1713200004,
            "instanceId": "instance-1",
            "source": "android",
        },
    }

    event = EvolutionMessagingAdapter.parse_inbound_event(payload)

    assert event.kind is MessageKind.AUDIO
    assert event.media_url == "https://cdn.example.com/voice.enc"
    assert event.metadata["media_key"] == "cHR0LW1lZGlhLWtleQ=="
