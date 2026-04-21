from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.dependencies import get_campaign_worker, require_internal_or_user
from core.services.campaign_worker import CampaignWorker

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


@router.post("/run", status_code=status.HTTP_200_OK)
async def run_campaign_worker(
    campaign_worker: Annotated[CampaignWorker, Depends(get_campaign_worker)],
    auth_context: Annotated[dict[str, object], Depends(require_internal_or_user)],
) -> dict[str, int]:
    del auth_context
    result = await campaign_worker.run_once()
    return {
        "processed": result.processed,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "duration_ms": result.duration_ms,
    }
