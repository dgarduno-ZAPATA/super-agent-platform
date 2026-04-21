from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.dependencies import get_current_user, get_dashboard_service
from core.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_dashboard_stats(
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
) -> dict[str, object]:
    del current_user
    metrics = await dashboard_service.get_operational_metrics()
    metrics["generated_at"] = datetime.now(UTC).isoformat()
    return metrics
