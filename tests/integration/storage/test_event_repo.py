from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from adapters.storage.repositories.event_repo import PostgresConversationEventRepository
from core.domain.conversation_event import ConversationEvent
from tests.integration.storage.conftest import run_async


def test_event_repo_append_and_dedup(clean_event_tables: None) -> None:
    repo = PostgresConversationEventRepository()
    conversation_id = uuid4()
    now = datetime.now(UTC)

    first_event = ConversationEvent(
        id=uuid4(),
        conversation_id=conversation_id,
        lead_id=None,
        event_type="inbound_message",
        payload={"message_id": "wamid-001", "body": "hola"},
        created_at=now,
        message_id="wamid-001",
    )
    duplicate_event = ConversationEvent(
        id=uuid4(),
        conversation_id=conversation_id,
        lead_id=None,
        event_type="inbound_message",
        payload={"message_id": "wamid-001", "body": "hola otra vez"},
        created_at=now,
        message_id="wamid-001",
    )

    inserted = run_async(repo.append(first_event))
    duplicated = run_async(repo.append(duplicate_event))
    events = run_async(repo.list_by_conversation(conversation_id))

    assert inserted is True
    assert duplicated is False
    assert len(events) == 1
    assert events[0].message_id == "wamid-001"
