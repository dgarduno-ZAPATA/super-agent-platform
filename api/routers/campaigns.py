from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from api.dependencies import get_audit_log_service, get_campaign_worker, require_internal_or_user
from core.services.campaign_worker import CampaignWorker
from core.services.audit_log_service import AuditLogService

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


@router.post("/run", status_code=status.HTTP_200_OK)
async def run_campaign_worker(
    request: Request,
    campaign_worker: Annotated[CampaignWorker, Depends(get_campaign_worker)],
    auth_context: Annotated[dict[str, object], Depends(require_internal_or_user)],
    audit_log_service: Annotated[AuditLogService, Depends(get_audit_log_service)],
) -> dict[str, int]:
    result = await campaign_worker.run_once()
    actor = str(auth_context.get("sub") or auth_context.get("auth_type") or "admin")
    client_host = request.client.host if request.client is not None else None
    await audit_log_service.log(
        actor=actor,
        action="campaign_started",
        resource_type="campaign",
        resource_id="manual_run",
        details={
            "processed": result.processed,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "duration_ms": result.duration_ms,
        },
        ip_address=client_host,
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "processed": result.processed,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "duration_ms": result.duration_ms,
    }
