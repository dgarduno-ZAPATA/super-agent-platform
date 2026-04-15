from datetime import datetime
from typing import Protocol

from core.domain.lead import Lead


class CRMProvider(Protocol):
    async def upsert_lead(self, lead: Lead) -> str:
        """Create or update a lead in the external CRM and return its external identifier."""

    async def change_stage(self, lead_id: str, new_stage: str, reason: str | None = None) -> None:
        """
        Move a lead to a new canonical business stage,
        preserving the optional business reason.
        """

    async def add_note(self, lead_id: str, note: str, author: str) -> None:
        """Attach an auditable note to a lead under the provided author identity."""

    async def assign_owner(self, lead_id: str, owner_id: str) -> None:
        """Assign responsibility for a lead to the provided owner identifier."""

    async def mark_do_not_contact(self, lead_id: str, reason: str) -> None:
        """Mark a lead as do-not-contact so future outreach can be safely suppressed."""

    async def schedule_reactivation(self, lead_id: str, not_before: datetime) -> None:
        """Register the earliest time at which a lead may re-enter reactivation workflows."""
