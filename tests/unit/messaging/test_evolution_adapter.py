import asyncio

import pytest

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


# ---------------------------------------------------------------------------
# Helpers for get_media_base64 tests
# ---------------------------------------------------------------------------


class _FakeSettings:
    evolution_base_url = "https://evo.example.com"
    evolution_api_key = "test-key"
    evolution_instance_name = "test-instance"


class _MockResponse:
    def __init__(self, status_code: int, json_data: object) -> None:
        self._status_code = status_code
        self._json_data = json_data

    @property
    def status_code(self) -> int:
        return self._status_code

    def json(self) -> object:
        return self._json_data


class _MockClient:
    def __init__(self, responses: list[_MockResponse]) -> None:
        self._responses = responses
        self._call_count = 0
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs: object) -> _MockResponse:
        self.calls.append({"url": url, **kwargs})
        response = self._responses[self._call_count]
        self._call_count += 1
        return response


async def _no_sleep(seconds: float) -> None:
    del seconds


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_media_base64_strips_data_prefix() -> None:
    response = _MockResponse(200, {"base64": "data:audio/ogg;base64,ABC123"})
    client = _MockClient([response])
    adapter = EvolutionMessagingAdapter(
        settings=_FakeSettings(),  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
    )

    result = await adapter.get_media_base64("msg-id-1", "5214421234567@s.whatsapp.net")

    assert result == "ABC123"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_get_media_base64_retries_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    responses = [
        _MockResponse(500, {}),
        _MockResponse(500, {}),
        _MockResponse(200, {"base64": "VALIDBASE64"}),
    ]
    client = _MockClient(responses)
    adapter = EvolutionMessagingAdapter(
        settings=_FakeSettings(),  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
    )

    result = await adapter.get_media_base64("msg-id-2", "5214421234567@s.whatsapp.net")

    assert result == "VALIDBASE64"
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_get_media_base64_returns_none_after_all_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    responses = [
        _MockResponse(500, {}),
        _MockResponse(500, {}),
        _MockResponse(500, {}),
    ]
    client = _MockClient(responses)
    adapter = EvolutionMessagingAdapter(
        settings=_FakeSettings(),  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
    )

    result = await adapter.get_media_base64("msg-id-3", "5214421234567@s.whatsapp.net")

    assert result is None
    assert len(client.calls) == 3
