from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.dependencies import get_audit_log_service, get_handoff_service
from core.services.audit_log_service import AuditLogService
from core.services.handoff_service import HandoffService

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


class ConversationStateResponse(BaseModel):
    lead_id: UUID
    state: str


@router.post(
    "/{lead_id}/take-control",
    status_code=status.HTTP_200_OK,
    response_model=ConversationStateResponse,
)
async def take_control(
    lead_id: UUID,
    request: Request,
    handoff_service: Annotated[HandoffService, Depends(get_handoff_service)],
    audit_log_service: Annotated[AuditLogService, Depends(get_audit_log_service)],
) -> ConversationStateResponse:
    try:
        session = await handoff_service.take_control(lead_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    client_host = request.client.host if request.client is not None else None
    await audit_log_service.log(
        actor="admin",
        action="handoff_taken",
        resource_type="conversation",
        resource_id=str(lead_id),
        ip_address=client_host,
        user_agent=request.headers.get("user-agent"),
    )
    return ConversationStateResponse(lead_id=session.lead_id, state=session.current_state)


@router.post(
    "/{lead_id}/release-control",
    status_code=status.HTTP_200_OK,
    response_model=ConversationStateResponse,
)
async def release_control(
    lead_id: UUID,
    handoff_service: Annotated[HandoffService, Depends(get_handoff_service)],
) -> ConversationStateResponse:
    try:
        session = await handoff_service.release_control(lead_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ConversationStateResponse(lead_id=session.lead_id, state=session.current_state)
