from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.services.dashboard_service import DashboardService


class FakeSessionRepository:
    async def count_not_in_states(self, states: set[str]) -> int:
        assert states == {"closed", "idle"}
        return 5

    async def count_by_state(self, state: str) -> int:
        assert state == "handoff_pending"
        return 2


class FakeConversationEventRepository:
    def __init__(self) -> None:
        self.last_since: datetime | None = None

    async def count_since(self, since: datetime) -> int:
        self.last_since = since
        return 42


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


class FakeCRMOutboxRepository:
    async def count_dlq_items(self) -> int:
        return 4


@pytest.mark.asyncio
async def test_dashboard_service_calculates_operational_metrics() -> None:
    events_repo = FakeConversationEventRepository()
    service = DashboardService(
        session_repository=FakeSessionRepository(),
        conversation_event_repository=events_repo,
        outbound_queue_repository=FakeOutboundQueueRepository(),
        crm_outbox_repository=FakeCRMOutboxRepository(),
    )

    metrics = await service.get_operational_metrics()

    assert metrics["active_sessions"] == 5
    assert metrics["pending_handoffs"] == 2
    assert metrics["crm_sync_errors"] == 4
    assert metrics["total_messages_last_24h"] == 42
    assert metrics["outbound_queue_stats"] == {
        "P0": {"pending": 3, "failed": 1},
        "P1": {"pending": 7, "failed": 0},
    }
    assert events_repo.last_since is not None
    assert (datetime.now(UTC) - events_repo.last_since).total_seconds() <= 24 * 3600 + 10
