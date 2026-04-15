from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SilencedUser(BaseModel):
    phone: str
    reason: str
    silenced_at: datetime
    silenced_by: str

    model_config = ConfigDict(frozen=True, strict=True)
