from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import structlog

from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import OutboundQueueRepository

logger = structlog.get_logger("super_agent_platform.core.services.campaign_worker")


class _TemplateValues(dict[str, object]):
    def __missing__(self, key: str) -> str:
        del key
        return ""


@dataclass(frozen=True, slots=True)
class CampaignRunResult:
    processed: int
    succeeded: int
    failed: int
    duration_ms: int


class CampaignWorker:
    def __init__(
        self,
        outbound_queue_repository: OutboundQueueRepository,
        messaging_provider: MessagingProvider,
        batch_size: int = 10,
        rate_limit_ms: int = 300,
    ) -> None:
        self._outbound_queue_repository = outbound_queue_repository
        self._messaging_provider = messaging_provider
        self._batch_size = batch_size
        self._rate_limit_ms = rate_limit_ms

    async def run_once(self) -> CampaignRunResult:
        started = perf_counter()
        items = await self._outbound_queue_repository.get_next_batch(limit=self._batch_size)

        succeeded = 0
        failed = 0
        for index, item in enumerate(items):
            try:
                phone = self._resolve_phone(item.lead_phone, item.payload)
                message = self._render_message(item.payload)
                if phone is None:
                    await self._outbound_queue_repository.mark_as_failed(item.id, "missing_phone")
                    failed += 1
                    logger.warning("campaign_item_skipped_missing_phone", item_id=str(item.id))
                elif not message:
                    await self._outbound_queue_repository.mark_as_failed(item.id, "missing_message")
                    failed += 1
                    logger.warning("campaign_item_skipped_missing_message", item_id=str(item.id))
                else:
                    await self._messaging_provider.send_text(
                        to=phone,
                        text=message,
                        correlation_id=str(item.id),
                    )
                    await self._outbound_queue_repository.mark_as_sent(item.id)
                    succeeded += 1
                    logger.info(
                        "campaign_item_sent",
                        item_id=str(item.id),
                        phone=phone,
                        priority=item.priority,
                    )
            except Exception as exc:
                await self._outbound_queue_repository.mark_as_failed(item.id, str(exc))
                failed += 1
                logger.exception("campaign_item_failed", item_id=str(item.id))

            if index < len(items) - 1 and self._rate_limit_ms > 0:
                await asyncio.sleep(self._rate_limit_ms / 1000)

        duration_ms = int((perf_counter() - started) * 1000)
        logger.info(
            "campaign_run_once_completed",
            processed=len(items),
            succeeded=succeeded,
            failed=failed,
            duration_ms=duration_ms,
        )
        return CampaignRunResult(
            processed=len(items),
            succeeded=succeeded,
            failed=failed,
            duration_ms=duration_ms,
        )

    @classmethod
    def _render_message(cls, payload: dict[str, object]) -> str:
        template = cls._read_string(payload.get("template")) or cls._read_string(payload.get("text"))
        if template is None:
            return ""

        variables = payload.get("variables")
        if isinstance(variables, dict):
            render_values = _TemplateValues({str(k): v for k, v in variables.items()})
            return template.format_map(render_values).strip()

        render_values = _TemplateValues({str(k): v for k, v in payload.items()})
        return template.format_map(render_values).strip()

    @staticmethod
    def _resolve_phone(lead_phone: str | None, payload: dict[str, object]) -> str | None:
        if lead_phone:
            normalized = lead_phone.strip()
            if normalized:
                return normalized

        for key in ("phone", "to"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _read_string(value: Any) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
        return None
