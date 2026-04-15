from __future__ import annotations

from typing import Protocol
from uuid import UUID

from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
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


class SilencedUserRepository(Protocol):
    async def is_silenced(self, phone: str) -> bool:
        """Return whether a canonical phone is currently silenced."""

    async def silence(self, phone: str, reason: str, silenced_by: str) -> None:
        """Create or refresh a silenced user record for a canonical phone."""

    async def unsilence(self, phone: str) -> None:
        """Remove the silenced marker for a canonical phone if it exists."""
