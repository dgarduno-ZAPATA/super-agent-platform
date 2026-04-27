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
        root_message = raw_payload.get("message")
        root_message_map = root_message if isinstance(root_message, dict) else {}
        data_payload = raw_payload.get("data")
        data_payload_map = data_payload if isinstance(data_payload, dict) else {}
        message_type_normalized = message_payload.messageType.strip().casefold()
        if (
            message_kind.value in {"audio", "ptt"}
            or "audio" in message_type_normalized
            or "ptt" in message_type_normalized
        ):
            logger.info(
                "evolution_audio_raw_payload_debug",
                raw_keys=list(raw_payload.keys()),
                message_keys=list(root_message_map.keys()),
                data_keys=list(data_payload_map.keys()) if "data" in raw_payload else [],
                has_audio_message="audioMessage" in root_message_map,
                has_ptt_message="pttMessage" in root_message_map,
            )
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

        data = raw_payload.get("data")
        if not isinstance(data, dict):
            return {}
        message = data.get("message")
        if not isinstance(message, dict):
            return {}
        audio_message = message.get("audioMessage")
        if not isinstance(audio_message, dict):
            return {}

        media_key = audio_message.get("mediaKey")
        file_enc_sha256 = audio_message.get("fileEncSha256")
        file_sha256 = audio_message.get("fileSha256")

        return {
            "media_key": media_key if isinstance(media_key, str) else None,
            "file_enc_sha256": file_enc_sha256 if isinstance(file_enc_sha256, str) else None,
            "file_sha256": file_sha256 if isinstance(file_sha256, str) else None,
        }
