from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OutboundQueueItem(BaseModel):
    id: UUID
    lead_id: UUID | None
    lead_phone: str | None = None
    campaign_id: UUID | None = None
    priority: int
    payload: dict[str, object]
    status: str
    scheduled_at: datetime
    sent_at: datetime | None = None
    attempts: int
    last_error: str | None = None

    model_config = ConfigDict(frozen=True, strict=True)
