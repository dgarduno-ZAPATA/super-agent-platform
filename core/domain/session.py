from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Session(BaseModel):
    id: UUID
    lead_id: UUID
    current_state: str
    context: dict[str, object]
    created_at: datetime
    updated_at: datetime
    last_event_at: datetime | None = None

    model_config = ConfigDict(frozen=True, strict=True)
