from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from core.domain.conversation_event import ConversationEvent
from core.domain.crm_outbox import OutboxItem
from core.domain.lead import LeadProfile
from core.domain.outbound_queue import OutboundQueueItem
from core.domain.session import Session


class SessionRepository(Protocol):
    async def get_by_lead_id(self, lead_id: UUID) -> Session | None:
        """Return the current session for a lead, if it exists."""

    async def upsert(self, session: Session) -> Session:
        """Insert or update a session and return the stored representation."""

    async def update_state(
        self, session_id: UUID, new_state: str, context: dict[str, object]
    ) -> None:
        """Update the canonical state and context of an existing session."""


class ConversationEventRepository(Protocol):
    async def append(self, event: ConversationEvent) -> bool:
        """
        Append a conversation event.

        Return False when an inbound message is rejected by the DB dedup constraint,
        otherwise return True when the event is persisted.
        """

    async def list_by_conversation(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[ConversationEvent]:
        """List the most recent events for a conversation up to the provided limit."""


class LeadProfileRepository(Protocol):
    async def get_by_phone(self, phone: str) -> LeadProfile | None:
        """Return a lead profile by canonical phone number, if present."""

    async def upsert_by_phone(self, profile: LeadProfile) -> LeadProfile:
        """Insert or update a lead profile using phone as the business key."""

    async def get_dormant_leads(self, days_inactive: int, limit: int = 100) -> list[LeadProfile]:
        """Return leads without recent activity based on profile recency heuristics."""


class OutboundQueueRepository(Protocol):
    async def enqueue(
        self,
        lead_id: UUID,
        campaign_id: UUID | None,
        payload: dict[str, object],
        priority: int,
        scheduled_at: datetime,
    ) -> UUID:
        """Insert a pending outbound item and return its id."""

    async def get_next_batch(self, limit: int = 10) -> list[OutboundQueueItem]:
        """Fetch next pending items with FOR UPDATE SKIP LOCKED semantics."""

    async def mark_as_sent(self, item_id: UUID) -> None:
        """Mark an outbound queue item as sent."""

    async def mark_as_failed(self, item_id: UUID, error: str) -> None:
        """Mark an outbound queue item as failed with an error reason."""


class CRMOutboxRepository(Protocol):
    async def enqueue_operation(
        self, aggregate_id: str, operation: str, payload: dict[str, object]
    ) -> UUID:
        """Insert a CRM operation into outbox as pending."""

    async def get_pending_batch(self, limit: int = 10) -> list[OutboxItem]:
        """Fetch pending CRM operations due for execution with SKIP LOCKED semantics."""

    async def mark_as_done(self, item_id: UUID) -> None:
        """Mark outbox operation as done."""

    async def mark_as_failed_with_retry(
        self, item_id: UUID, error: str, next_retry_at: datetime, attempt: int
    ) -> None:
        """Mark outbox operation as pending with retry metadata."""

    async def move_to_dlq(self, item_id: UUID, error: str) -> None:
        """Move operation to dead-letter queue when retries are exhausted."""


class SilencedUserRepository(Protocol):
    async def is_silenced(self, phone: str) -> bool:
        """Return whether a canonical phone is currently silenced."""

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        """Create or refresh a silenced user record for a canonical phone."""

    async def unsilence(self, phone: str) -> None:
        """Remove the silenced marker for a canonical phone if it exists."""
