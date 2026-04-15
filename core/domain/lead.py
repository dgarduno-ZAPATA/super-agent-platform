from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True, slots=True)
class Lead:
    external_id: str | None = None
    phone: str = ""
    name: str = ""
    stage: str = ""
    source: str = ""
    attributes: dict[str, object] = field(default_factory=dict)


class LeadProfile(BaseModel):
    id: UUID
    external_crm_id: str | None = None
    phone: str
    name: str | None = None
    source: str | None = None
    attributes: dict[str, object]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(frozen=True, strict=True)
