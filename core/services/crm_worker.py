from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from core.brand.loader import load_brand_config
from core.brand.schema import Brand
from core.domain.lead import Lead
from core.ports.crm_provider import CRMProvider
from core.ports.repositories import CRMOutboxRepository

logger = structlog.get_logger("super_agent_platform.core.services.crm_worker")


class CRMSyncWorker:
    def __init__(
        self,
        crm_outbox_repository: CRMOutboxRepository,
        crm_provider: CRMProvider,
        brand_config: Brand | None = None,
    ) -> None:
        self._crm_outbox_repository = crm_outbox_repository
        self._crm_provider = crm_provider
        self._brand_config = brand_config or load_brand_config()

    async def process_batch(self, batch_size: int = 10) -> None:
        items = await self._crm_outbox_repository.get_pending_batch(limit=batch_size)
        logger.info("crm_sync_batch_loaded", batch_size=batch_size, items=len(items))

        for item in items:
            try:
                logger.info(
                    "crm_sync_item_dispatching",
                    item_id=str(item.id),
                    operation=item.operation,
                )
                await self._dispatch_operation(item.operation, item.payload)
                await self._crm_outbox_repository.mark_as_done(item.id)
                logger.info("crm_sync_item_done", item_id=str(item.id), operation=item.operation)
            except Exception as exc:
                next_attempt = item.attempts + 1
                if next_attempt < 3:
                    next_retry_at = datetime.now(UTC) + timedelta(minutes=next_attempt * 5)
                    await self._crm_outbox_repository.mark_as_failed_with_retry(
                        item_id=item.id,
                        error=str(exc),
                        next_retry_at=next_retry_at,
                        attempt=next_attempt,
                    )
                    logger.warning(
                        "crm_sync_item_retry_scheduled",
                        item_id=str(item.id),
                        attempt=next_attempt,
                        next_retry_at=next_retry_at.isoformat(),
                    )
                else:
                    await self._crm_outbox_repository.move_to_dlq(item.id, str(exc))
                    logger.error(
                        "crm_sync_item_moved_to_dlq",
                        item_id=str(item.id),
                        attempt=next_attempt,
                    )

        await self._check_dlq_alerts()

    async def _check_dlq_alerts(self) -> None:
        """
        Verify DLQ state and emit alerts when configured thresholds are exceeded.
        Best-effort: this method never raises.
        """
        try:
            dlq_count = await self._crm_outbox_repository.count_dlq_items()
            pending_count = await self._crm_outbox_repository.count_pending_items()
            threshold = self._brand_config.brand.alerts.crm_dlq_threshold
            pending_threshold = self._brand_config.brand.alerts.crm_pending_threshold

            if dlq_count >= threshold:
                logger.warning(
                    "crm_dlq_threshold_exceeded",
                    dlq_count=dlq_count,
                    threshold=threshold,
                )
                try:
                    import sentry_sdk

                    with sentry_sdk.push_scope() as scope:
                        scope.set_extra("dlq_count", dlq_count)
                        scope.set_extra("threshold", threshold)
                        sentry_sdk.capture_message(
                            f"CRM DLQ threshold exceeded: {dlq_count} items",
                            level="warning",
                        )
                except Exception:
                    pass

            if pending_count >= pending_threshold:
                logger.warning(
                    "crm_pending_threshold_exceeded",
                    pending_count=pending_count,
                    threshold=pending_threshold,
                )

            logger.debug(
                "crm_outbox_health",
                dlq_count=dlq_count,
                pending_count=pending_count,
            )
        except Exception as exc:
            logger.warning(
                "crm_dlq_check_failed",
                reason=str(exc),
            )

    async def _dispatch_operation(self, operation: str, payload: dict[str, object]) -> None:
        if operation == "upsert_lead":
            await self._crm_provider.upsert_lead(
                Lead(
                    external_id=self._to_optional_str(payload.get("external_id")),
                    phone=self._to_str(payload.get("phone")),
                    name=self._to_str(payload.get("name"), default=""),
                    stage=self._to_str(payload.get("stage"), default=""),
                    source=self._to_str(payload.get("source"), default=""),
                    attributes=payload,
                )
            )
            return

        if operation == "change_stage":
            await self._crm_provider.change_stage(
                lead_id=self._to_str(payload.get("lead_id")),
                new_stage=self._to_str(payload.get("new_stage")),
                reason=self._to_optional_str(payload.get("reason")),
                phone=self._to_optional_str(payload.get("phone")),
            )
            return

        if operation == "add_note":
            await self._crm_provider.add_note(
                lead_id=self._to_str(payload.get("lead_id")),
                note=self._to_str(payload.get("note")),
                author=self._to_str(payload.get("author"), default="system"),
            )
            return

        raise ValueError(f"unsupported crm operation: {operation}")

    @staticmethod
    def _to_str(value: object, default: str | None = None) -> str:
        if isinstance(value, str) and value:
            return value
        if default is not None:
            return default
        raise ValueError("required string value is missing")

    @staticmethod
    def _to_optional_str(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None
