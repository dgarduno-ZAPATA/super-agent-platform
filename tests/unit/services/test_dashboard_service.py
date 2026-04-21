from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.services.dashboard_service import DashboardService


class FakeSessionRepository:
    def __init__(self) -> None:
        self.excluded_states: set[str] | None = None
        self.active_since: datetime | None = None

    async def count_not_in_states(self, states: set[str]) -> int:
        del states
        return 0

    async def count_by_state(self, state: str) -> int:
        assert state == "handoff_pending"
        return 2

    async def count_active_since(
        self, since: datetime, excluded_states: set[str] | None = None
    ) -> int:
        self.active_since = since
        self.excluded_states = excluded_states
        return 5

    async def count_human_control_sessions(self) -> int:
        return 3

    async def count_grouped_by_state(self) -> dict[str, int]:
        return {"greeting": 2, "handoff_active": 3}


class FakeLeadProfileRepository:
    def __init__(self) -> None:
        self.created_since: datetime | None = None

    async def count_total(self) -> int:
        return 25

    async def count_created_since(self, since: datetime) -> int:
        self.created_since = since
        return 4

    async def count_grouped_by_stage(self) -> dict[str, int]:
        return {"contacted": 10, "qualified": 8, "unknown": 7}


class FakeConversationEventRepository:
    def __init__(self) -> None:
        self.last_since: datetime | None = None
        self.by_type_calls: list[tuple[str, datetime]] = []

    async def count_since(self, since: datetime) -> int:
        self.last_since = since
        return 42

    async def count_by_type_since(self, event_type: str, since: datetime) -> int:
        self.by_type_calls.append((event_type, since))
        if event_type == "outbound_message":
            return 12
        if event_type == "handoff_requested":
            return 6
        return 0

    async def average_response_time_minutes_since(self, since: datetime) -> float | None:
        del since
        return 7.5


class FakeOutboundQueueRepository:
    async def count_by_priority_and_status(
        self, priorities: set[int], statuses: set[str]
    ) -> dict[int, dict[str, int]]:
        assert priorities == {0, 1}
        assert statuses == {"pending", "failed"}
        return {
            0: {"pending": 3, "failed": 1},
            1: {"pending": 7},
        }

    async def count_by_statuses(self, statuses: set[str]) -> int:
        assert statuses == {"pending", "processing"}
        return 11


class FakeCRMOutboxRepository:
    async def count_dlq_items(self) -> int:
        return 4

    async def count_pending_items(self) -> int:
        return 9


@pytest.mark.asyncio
async def test_dashboard_service_calculates_operational_metrics() -> None:
    session_repo = FakeSessionRepository()
    lead_repo = FakeLeadProfileRepository()
    events_repo = FakeConversationEventRepository()
    service = DashboardService(
        session_repository=session_repo,
        lead_profile_repository=lead_repo,
        conversation_event_repository=events_repo,
        outbound_queue_repository=FakeOutboundQueueRepository(),
        crm_outbox_repository=FakeCRMOutboxRepository(),
    )

    metrics = await service.get_operational_metrics()

    assert metrics["active_sessions"] == 5
    assert metrics["pending_handoffs"] == 2
    assert metrics["sessions_in_handoff"] == 3
    assert metrics["sessions_by_fsm_state"] == {"greeting": 2, "handoff_active": 3}
    assert metrics["total_leads"] == 25
    assert metrics["new_leads_today"] == 4
    assert metrics["leads_by_stage"] == {"contacted": 10, "qualified": 8, "unknown": 7}
    assert metrics["messages_sent_today"] == 12
    assert metrics["messages_pending"] == 11
    assert metrics["crm_sync_pending"] == 9
    assert metrics["crm_sync_dlq"] == 4
    assert metrics["crm_sync_errors"] == 4
    assert metrics["handoffs_today"] == 6
    assert metrics["avg_response_time_minutes"] == 7.5
    assert metrics["total_messages_last_24h"] == 42
    assert metrics["outbound_queue_stats"] == {
        "P0": {"pending": 3, "failed": 1},
        "P1": {"pending": 7, "failed": 0},
    }
    assert events_repo.last_since is not None
    assert session_repo.active_since is not None
    assert session_repo.excluded_states == {"closed"}


@pytest.mark.asyncio
async def test_active_sessions_count_excludes_closed() -> None:
    session_repo = FakeSessionRepository()
    service = DashboardService(
        session_repository=session_repo,
        lead_profile_repository=FakeLeadProfileRepository(),
        conversation_event_repository=FakeConversationEventRepository(),
        outbound_queue_repository=FakeOutboundQueueRepository(),
        crm_outbox_repository=FakeCRMOutboxRepository(),
    )

    await service.get_operational_metrics()

    assert session_repo.excluded_states == {"closed"}


@pytest.mark.asyncio
async def test_sessions_in_handoff_only_counts_human_control() -> None:
    service = DashboardService(
        session_repository=FakeSessionRepository(),
        lead_profile_repository=FakeLeadProfileRepository(),
        conversation_event_repository=FakeConversationEventRepository(),
        outbound_queue_repository=FakeOutboundQueueRepository(),
        crm_outbox_repository=FakeCRMOutboxRepository(),
    )

    metrics = await service.get_operational_metrics()

    assert metrics["sessions_in_handoff"] == 3


@pytest.mark.asyncio
async def test_new_leads_today_uses_created_at_filter() -> None:
    lead_repo = FakeLeadProfileRepository()
    service = DashboardService(
        session_repository=FakeSessionRepository(),
        lead_profile_repository=lead_repo,
        conversation_event_repository=FakeConversationEventRepository(),
        outbound_queue_repository=FakeOutboundQueueRepository(),
        crm_outbox_repository=FakeCRMOutboxRepository(),
    )

    await service.get_operational_metrics()

    assert lead_repo.created_since is not None
    now = datetime.now(UTC)
    expected_floor = datetime(now.year, now.month, now.day, tzinfo=UTC)
    assert expected_floor <= lead_repo.created_since <= expected_floor + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_crm_sync_pending_reads_from_outbox() -> None:
    service = DashboardService(
        session_repository=FakeSessionRepository(),
        lead_profile_repository=FakeLeadProfileRepository(),
        conversation_event_repository=FakeConversationEventRepository(),
        outbound_queue_repository=FakeOutboundQueueRepository(),
        crm_outbox_repository=FakeCRMOutboxRepository(),
    )

    metrics = await service.get_operational_metrics()

    assert metrics["crm_sync_pending"] == 9
