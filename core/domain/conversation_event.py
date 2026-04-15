from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ConversationEvent(BaseModel):
    id: UUID
    conversation_id: UUID
    lead_id: UUID | None = None
    event_type: str
    payload: dict[str, object]
    created_at: datetime
    message_id: str | None = None

    model_config = ConfigDict(frozen=True, strict=True)
