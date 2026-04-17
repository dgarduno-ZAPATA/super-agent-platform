from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.domain.conversation_event import ConversationEvent
from core.domain.session import Session
from core.services.handoff_service import HandoffService


class FakeSessionRepository:
    def __init__(self, sessions: list[Session]) -> None:
        self.by_lead_id: dict[UUID, Session] = {session.lead_id: session for session in sessions}

    async def get_by_lead_id(self, lead_id: UUID) -> Session | None:
        return self.by_lead_id.get(lead_id)

    async def upsert(self, session: Session) -> Session:
        self.by_lead_id[session.lead_id] = session
        return session

    async def update_state(
        self, session_id: UUID, new_state: str, context: dict[str, object]
    ) -> None:
        for lead_id, session in self.by_lead_id.items():
            if session.id == session_id:
                now = datetime.now(UTC)
                self.by_lead_id[lead_id] = Session(
                    id=session.id,
                    lead_id=session.lead_id,
                    current_state=new_state,
                    context=context,
                    created_at=session.created_at,
                    updated_at=now,
                    last_event_at=session.last_event_at,
                )
                return
        raise ValueError(f"session not found by id={session_id}")


class FakeConversationEventRepository:
    def __init__(self) -> None:
        self.events: list[ConversationEvent] = []

    async def append(self, event: ConversationEvent) -> bool:
        self.events.append(event)
        return True

    async def list_by_conversation(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[ConversationEvent]:
        return [item for item in self.events if item.conversation_id == conversation_id][:limit]


def _session(current_state: str = "handoff_pending") -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        lead_id=uuid4(),
        current_state=current_state,
        context={"existing": "context"},
        created_at=now,
        updated_at=now,
        last_event_at=now,
    )


@pytest.mark.asyncio
async def test_take_control_updates_state_and_appends_system_event() -> None:
    existing = _session(current_state="handoff_pending")
    session_repo = FakeSessionRepository([existing])
    event_repo = FakeConversationEventRepository()
    service = HandoffService(
        session_repository=session_repo,
        conversation_event_repository=event_repo,
    )

    updated = await service.take_control(existing.lead_id)

    assert updated.current_state == "handoff_active"
    assert len(event_repo.events) == 1
    assert event_repo.events[0].event_type == "system_agent_took_control"
    assert event_repo.events[0].lead_id == existing.lead_id


@pytest.mark.asyncio
async def test_release_control_updates_state_and_appends_system_event() -> None:
    existing = _session(current_state="handoff_active")
    session_repo = FakeSessionRepository([existing])
    event_repo = FakeConversationEventRepository()
    service = HandoffService(
        session_repository=session_repo,
        conversation_event_repository=event_repo,
    )

    updated = await service.release_control(existing.lead_id)

    assert updated.current_state == "idle"
    assert len(event_repo.events) == 1
    assert event_repo.events[0].event_type == "system_agent_released_control"
    assert event_repo.events[0].lead_id == existing.lead_id


@pytest.mark.asyncio
async def test_take_control_raises_when_lead_session_not_found() -> None:
    session_repo = FakeSessionRepository([])
    event_repo = FakeConversationEventRepository()
    service = HandoffService(
        session_repository=session_repo,
        conversation_event_repository=event_repo,
    )

    with pytest.raises(ValueError, match="session not found"):
        await service.take_control(uuid4())

    assert event_repo.events == []
