from __future__ import annotations

import structlog

from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import OutboundQueueRepository, SilencedUserRepository

logger = structlog.get_logger("super_agent_platform.core.services.queue_worker")


class OutboundQueueWorker:
    def __init__(
        self,
        outbound_queue_repository: OutboundQueueRepository,
        messaging_provider: MessagingProvider,
        silenced_user_repository: SilencedUserRepository,
    ) -> None:
        self._outbound_queue_repository = outbound_queue_repository
        self._messaging_provider = messaging_provider
        self._silenced_user_repository = silenced_user_repository

    async def process_batch(self, batch_size: int = 10) -> None:
        items = await self._outbound_queue_repository.get_next_batch(limit=batch_size)
        logger.info("outbound_queue_batch_loaded", batch_size=batch_size, items=len(items))

        for item in items:
            phone = item.lead_phone
            if phone is None:
                await self._outbound_queue_repository.mark_as_failed(
                    item.id, "missing_phone_for_lead"
                )
                logger.warning("outbound_queue_item_failed_no_phone", item_id=str(item.id))
                continue

            is_silenced = await self._silenced_user_repository.is_silenced(phone)
            if is_silenced:
                await self._outbound_queue_repository.mark_as_failed(
                    item.id, "lead_silenced_opt_out"
                )
                logger.info(
                    "outbound_queue_item_skipped_silenced",
                    item_id=str(item.id),
                    phone=phone,
                )
                continue

            text = item.payload.get("text")
            if not isinstance(text, str) or not text.strip():
                await self._outbound_queue_repository.mark_as_failed(
                    item.id, "missing_text_payload"
                )
                logger.warning(
                    "outbound_queue_item_failed_no_text",
                    item_id=str(item.id),
                    phone=phone,
                )
                continue

            try:
                await self._messaging_provider.send_text(
                    to=phone,
                    text=text,
                    correlation_id=str(item.id),
                )
                await self._outbound_queue_repository.mark_as_sent(item.id)
                logger.info("outbound_queue_item_sent", item_id=str(item.id), phone=phone)
            except Exception as exc:
                await self._outbound_queue_repository.mark_as_failed(item.id, str(exc))
                logger.exception(
                    "outbound_queue_item_send_failed",
                    item_id=str(item.id),
                    phone=phone,
                )
