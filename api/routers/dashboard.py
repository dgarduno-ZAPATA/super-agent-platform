from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.dependencies import get_dashboard_service
from core.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_dashboard_stats(
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
) -> dict[str, object]:
    return await dashboard_service.get_operational_metrics()
