from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import get_current_user, get_replay_engine
from core.services.replay_engine import ReplayEngine

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])


class ReplayRequest(BaseModel):
    until_event_id: UUID | None = None
    dry_run: bool = True


@router.get("/{lead_id}/trace", status_code=status.HTTP_200_OK)
async def get_lead_trace(
    lead_id: UUID,
    replay_engine: Annotated[ReplayEngine, Depends(get_replay_engine)],
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
) -> dict[str, object]:
    del current_user
    try:
        return await replay_engine.build_trace(lead_id=lead_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{lead_id}/replay", status_code=status.HTTP_200_OK)
async def replay_lead_conversation(
    lead_id: UUID,
    request: ReplayRequest,
    replay_engine: Annotated[ReplayEngine, Depends(get_replay_engine)],
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
) -> dict[str, object]:
    del current_user
    try:
        return await replay_engine.replay_conversation(
            lead_id=lead_id,
            until_event_id=request.until_event_id,
            dry_run=request.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
