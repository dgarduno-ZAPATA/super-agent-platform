from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OutboxItem(BaseModel):
    id: UUID
    aggregate_id: str
    operation: str
    payload: dict[str, object]
    status: str
    attempts: int
    next_retry_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(frozen=True, strict=True)


class DLQItem(BaseModel):
    id: UUID
    original_outbox_id: UUID
    payload: dict[str, object]
    error: str
    moved_at: datetime

    model_config = ConfigDict(frozen=True, strict=True)
