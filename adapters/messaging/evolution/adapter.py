from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from pydantic import ValidationError

from adapters.messaging.evolution.normalizers import (
    extract_text,
    normalize_message_type,
    normalize_phone,
)
from adapters.messaging.evolution.payloads import (
    EvolutionMessagePayload,
    EvolutionWebhookEnvelope,
)
from core.config import Settings
from core.domain.messaging import (
    InboundEvent,
    InvalidInboundPayloadError,
    MessageDeliveryReceipt,
    MessageKind,
    UnsupportedEventTypeError,
)
from core.ports.messaging_provider import MessagingProvider

logger = structlog.get_logger("super_agent_platform.adapters.messaging.evolution.adapter")


class EvolutionMessagingAdapter(MessagingProvider):
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=self._settings.evolution_base_url,
            headers={
                "apikey": self._settings.evolution_api_key,
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        return await self._send_message(
            endpoint="/message/sendText",
            payload={"number": to, "text": text},
            correlation_id=correlation_id,
        )

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        return await self._send_message(
            endpoint="/message/sendMedia",
            payload={"number": to, "mediatype": "image", "media": image_url, "caption": caption},
            correlation_id=correlation_id,
        )

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        return await self._send_message(
            endpoint="/message/sendMedia",
            payload={
                "number": to,
                "mediatype": "document",
                "media": document_url,
                "fileName": filename,
            },
            correlation_id=correlation_id,
        )

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        return await self._send_message(
            endpoint="/message/sendWhatsAppAudio",
            payload={"number": to, "audio": audio_url},
            correlation_id=correlation_id,
        )

    async def mark_read(self, message_id: str) -> None:
        await self._client.post(
            f"/chat/markMessageAsRead/{self._settings.evolution_instance_name}",
            json={"messageId": message_id},
        )

    async def _send_message(
        self, endpoint: str, payload: dict[str, Any], correlation_id: str
    ) -> MessageDeliveryReceipt:
        request_payload = dict(payload)
        raw_number = request_payload.get("number")
        if isinstance(raw_number, str):
            request_payload["number"] = self._normalize_outbound_number(raw_number)

        logger.debug(
            "evolution_outbound_request",
            endpoint=endpoint,
            instance=self._settings.evolution_instance_name,
            correlation_id=correlation_id,
            payload=request_payload,
        )
        response = await self._client.post(
            f"{endpoint}/{self._settings.evolution_instance_name}",
            json=request_payload,
        )
        response.raise_for_status()

        body = response.json()
        message_id = str(body.get("key", {}).get("id", correlation_id))
        message_type = str(request_payload.get("mediatype", "")).strip().lower() or "text"
        recipient_phone = str(request_payload.get("number", ""))
        logger.info(
            "evolution_message_accepted",
            to=recipient_phone,
            provider_message_id=message_id,
            message_type=message_type,
        )

        return MessageDeliveryReceipt(
            message_id=message_id,
            provider="evolution",
            status="accepted",
            correlation_id=correlation_id,
            metadata={"endpoint": endpoint},
        )

    @staticmethod
    def _normalize_outbound_number(number: str) -> str:
        normalized = normalize_phone(number)
        return normalized if normalized is not None else number.strip()

    @staticmethod
    def parse_inbound_event(raw_payload: dict[str, object]) -> InboundEvent:
        try:
            envelope = EvolutionWebhookEnvelope.model_validate(raw_payload)
        except ValidationError as exc:
            raise InvalidInboundPayloadError(f"invalid Evolution webhook payload: {exc}") from exc

        if envelope.event not in {"messages.upsert", "message.upsert"}:
            raise UnsupportedEventTypeError(f"unsupported Evolution event: {envelope.event}")

        if not isinstance(envelope.data, EvolutionMessagePayload):
            try:
                message_payload = EvolutionMessagePayload.model_validate(envelope.data)
            except ValidationError as exc:
                raise InvalidInboundPayloadError(
                    f"invalid Evolution message payload: {exc}"
                ) from exc
        else:
            message_payload = envelope.data

        from_phone = normalize_phone(message_payload.key.remoteJid)
        if from_phone is None:
            raise InvalidInboundPayloadError("invalid inbound sender: group or malformed jid")

        message_kind = normalize_message_type(message_payload.messageType)
        text = extract_text(message_payload)
        media_url = EvolutionMessagingAdapter._extract_media_url(message_payload)
        received_at = EvolutionMessagingAdapter._parse_received_at(message_payload.messageTimestamp)
        audio_crypto_metadata = EvolutionMessagingAdapter._extract_audio_crypto_metadata(
            raw_payload=raw_payload,
            message_kind=message_kind,
        )

        return InboundEvent(
            message_id=message_payload.key.id,
            from_phone=from_phone,
            kind=message_kind,
            text=text,
            media_url=media_url,
            raw_metadata={
                "instance": envelope.instance,
                "event": envelope.event,
                "message_type": message_payload.messageType,
                "push_name": message_payload.pushName,
                "remote_jid": message_payload.key.remoteJid,
                "participant": message_payload.key.participant,
            },
            received_at=received_at,
            sender_id=message_payload.key.remoteJid,
            channel="whatsapp",
            event_type="inbound_message",
            occurred_at=received_at,
            metadata={
                "instance": envelope.instance,
                "event": envelope.event,
                "message_type": message_payload.messageType,
                **audio_crypto_metadata,
            },
        )

    @staticmethod
    def _extract_media_url(payload: EvolutionMessagePayload) -> str | None:
        message = payload.message

        if message.imageMessage is not None:
            return message.imageMessage.url
        if message.audioMessage is not None:
            return message.audioMessage.url
        if message.pttMessage is not None:
            return message.pttMessage.url
        if message.documentMessage is not None:
            return message.documentMessage.url
        if message.videoMessage is not None:
            return message.videoMessage.url
        if message.stickerMessage is not None:
            return message.stickerMessage.url

        return None

    @staticmethod
    def _parse_received_at(timestamp: int | str | None) -> datetime:
        if timestamp is None:
            return datetime.now(UTC)

        try:
            parsed_timestamp = int(timestamp)
        except (TypeError, ValueError):
            return datetime.now(UTC)

        return datetime.fromtimestamp(parsed_timestamp, tz=UTC)

    @staticmethod
    def _extract_audio_crypto_metadata(
        raw_payload: dict[str, object],
        message_kind: MessageKind,
    ) -> dict[str, object]:
        if message_kind is not MessageKind.AUDIO:
            return {}

        candidates = EvolutionMessagingAdapter._audio_crypto_candidates(raw_payload)
        media_key = EvolutionMessagingAdapter._first_non_empty_string(
            candidates,
            ("mediaKey", "media_key", "mediakey"),
        )
        file_enc_sha256 = EvolutionMessagingAdapter._first_non_empty_string(
            candidates,
            ("fileEncSha256", "file_enc_sha256"),
        )
        file_sha256 = EvolutionMessagingAdapter._first_non_empty_string(
            candidates,
            ("fileSha256", "file_sha256"),
        )

        if media_key is None:
            media_key = EvolutionMessagingAdapter._recursive_find_first_string(
                raw_payload,
                ("mediaKey", "media_key"),
            )
        if file_enc_sha256 is None:
            file_enc_sha256 = EvolutionMessagingAdapter._recursive_find_first_string(
                raw_payload,
                ("fileEncSha256", "file_enc_sha256"),
            )
        if file_sha256 is None:
            file_sha256 = EvolutionMessagingAdapter._recursive_find_first_string(
                raw_payload,
                ("fileSha256", "file_sha256"),
            )

        return {
            "media_key": media_key,
            "file_enc_sha256": file_enc_sha256,
            "file_sha256": file_sha256,
        }

    @staticmethod
    def _audio_crypto_candidates(raw_payload: dict[str, object]) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []

        def _add_candidate(value: object) -> None:
            if isinstance(value, dict):
                candidates.append(value)

        data = raw_payload.get("data")
        data_map = data if isinstance(data, dict) else {}
        message = data_map.get("message")
        message_map = message if isinstance(message, dict) else {}
        root_message = raw_payload.get("message")
        root_message_map = root_message if isinstance(root_message, dict) else {}

        for container in (
            raw_payload,
            data_map,
            message_map,
            root_message_map,
            data_map.get("audioMessage"),
            data_map.get("pttMessage"),
            message_map.get("audioMessage"),
            message_map.get("pttMessage"),
            root_message_map.get("audioMessage"),
            root_message_map.get("pttMessage"),
            raw_payload.get("audioMessage"),
            raw_payload.get("pttMessage"),
        ):
            _add_candidate(container)

        return candidates

    @staticmethod
    def _first_non_empty_string(
        candidates: list[dict[str, object]],
        keys: tuple[str, ...],
    ) -> str | None:
        for candidate in candidates:
            for key in keys:
                value = candidate.get(key)
                if isinstance(value, str):
                    normalized = value.strip()
                    if normalized:
                        return normalized
        return None

    @staticmethod
    def _recursive_find_first_string(payload: object, keys: tuple[str, ...]) -> str | None:
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, str):
                    normalized = value.strip()
                    if normalized:
                        return normalized
            for value in payload.values():
                nested = EvolutionMessagingAdapter._recursive_find_first_string(value, keys)
                if nested is not None:
                    return nested
            return None
        if isinstance(payload, list):
            for item in payload:
                nested = EvolutionMessagingAdapter._recursive_find_first_string(item, keys)
                if nested is not None:
                    return nested
        return None
