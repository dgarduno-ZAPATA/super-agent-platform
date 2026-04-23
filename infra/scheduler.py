from __future__ import annotations

from typing import Any

import httpx
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from adapters.crm.monday_adapter import MondayCRMAdapter
from adapters.storage.repositories.crm_outbox_repo import PostgresCRMOutboxRepository
from core.config import Settings
from core.services.crm_worker import CRMSyncWorker

logger = structlog.get_logger("super_agent_platform.infra.scheduler")


def start_campaign_scheduler(app: FastAPI, settings: Settings) -> AsyncIOScheduler | None:
    if not settings.campaign_scheduler_enabled:
        logger.info("campaign_scheduler_disabled")
        return None

    scheduler = AsyncIOScheduler()

    async def _run_campaign_worker() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://super-agent-platform.local",
        ) as client:
            response = await client.post(
                "/api/v1/campaigns/run",
                headers={"X-Internal-Token": settings.internal_token},
                timeout=30.0,
            )
            if response.status_code != 200:
                logger.warning(
                    "campaign_scheduler_run_failed",
                    status_code=response.status_code,
                    response_text=response.text,
                )
                return
            payload: dict[str, Any] = response.json()
            logger.info(
                "campaign_scheduler_run_completed",
                processed=payload.get("processed"),
                succeeded=payload.get("succeeded"),
                failed=payload.get("failed"),
                duration_ms=payload.get("duration_ms"),
            )

    async def _run_crm_sync_worker() -> None:
        if not settings.monday_api_key.strip() or not settings.monday_board_id.strip():
            logger.warning(
                "crm_sync_worker_skipped_missing_config",
                monday_api_key_set=bool(settings.monday_api_key.strip()),
                monday_board_id_set=bool(settings.monday_board_id.strip()),
            )
            return

        crm_worker = CRMSyncWorker(
            crm_outbox_repository=PostgresCRMOutboxRepository(),
            crm_provider=MondayCRMAdapter(
                api_key=settings.monday_api_key,
                board_id=settings.monday_board_id,
            ),
        )
        try:
            await crm_worker.process_batch(batch_size=10)
        except Exception:
            logger.exception("crm_sync_worker_run_failed")

    scheduler.add_job(
        _run_campaign_worker,
        "interval",
        seconds=settings.campaign_scheduler_interval_seconds,
        id="campaign_worker_job",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_crm_sync_worker,
        "interval",
        seconds=30,
        id="crm_sync_worker_job",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "campaign_scheduler_started",
        interval_seconds=settings.campaign_scheduler_interval_seconds,
    )
    logger.info(
        "crm_sync_worker_started",
        interval_seconds=30,
        job_id="crm_sync_worker_job",
    )
    return scheduler


def stop_campaign_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    if scheduler is None:
        return
    scheduler.shutdown(wait=False)
    logger.info("campaign_scheduler_stopped")
