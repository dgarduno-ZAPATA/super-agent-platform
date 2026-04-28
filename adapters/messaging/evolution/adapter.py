from __future__ import annotations

import asyncio
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
    UnsupportedEventTypeError,
)
from core.ports.messaging_provider import MessagingProvider
from core.utils.human_delay import human_delay

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
        await self._send_typing(to=to)
        await human_delay(text=text, correlation_id=correlation_id)
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

    async def _send_typing(self, to: str) -> None:
        try:
            normalized_number = self._normalize_outbound_number(to)
            await self._client.post(
                f"/chat/sendPresence/{self._settings.evolution_instance_name}",
                json={
                    "number": normalized_number,
                    "options": {"presence": "composing"},
                },
            )
            logger.debug("typing_presence_sent", to=normalized_number[:4] + "***")
        except Exception as exc:
            logger.warning(
                "typing_presence_failed",
                to=to[:4] + "***",
                reason=str(exc),
            )

    async def get_media_base64(
        self,
        message_id: str,
        sender_id: str,
        from_me: bool = False,
    ) -> str | None:
        url = (
            f"{self._settings.evolution_base_url.rstrip('/')}"
            f"/chat/getBase64FromMediaMessage"
            f"/{self._settings.evolution_instance_name}"
        )
        payload = {
            "message": {
                "key": {
                    "remoteJid": sender_id,
                    "id": message_id,
                    "fromMe": from_me,
                }
            },
            "convertToMp4": False,
        }

        for attempt in range(1, 4):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code in (200, 201):
                    data = response.json()
                    base64_raw: str | None = None
                    if isinstance(data, dict):
                        base64_raw = data.get("base64") or data.get("media") or data.get("data")
                    elif isinstance(data, str):
                        base64_raw = data

                    if base64_raw:
                        if "base64," in base64_raw:
                            base64_raw = base64_raw.split("base64,", 1)[1]
                        logger.info(
                            "evolution_audio_base64_retrieved",
                            attempt=attempt,
                            message_id=message_id,
                            size=len(base64_raw),
                        )
                        return base64_raw

            except Exception as exc:
                logger.warning(
                    "evolution_audio_base64_attempt_failed",
                    attempt=attempt,
                    message_id=message_id,
                    error=str(exc),
                )

            if attempt < 3:
                await asyncio.sleep(2.0)

        logger.error(
            "evolution_audio_base64_all_retries_failed",
            message_id=message_id,
        )
        return None

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
