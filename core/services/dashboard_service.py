from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.ports.repositories import (
    ConversationEventRepository,
    CRMOutboxRepository,
    OutboundQueueRepository,
    SessionRepository,
)


class DashboardService:
    def __init__(
        self,
        session_repository: SessionRepository,
        conversation_event_repository: ConversationEventRepository,
        outbound_queue_repository: OutboundQueueRepository,
        crm_outbox_repository: CRMOutboxRepository,
    ) -> None:
        self._session_repository = session_repository
        self._conversation_event_repository = conversation_event_repository
        self._outbound_queue_repository = outbound_queue_repository
        self._crm_outbox_repository = crm_outbox_repository

    async def get_operational_metrics(self) -> dict[str, object]:
        active_sessions = await self._session_repository.count_not_in_states({"closed", "idle"})
        pending_handoffs = await self._session_repository.count_by_state("handoff_pending")
        outbound_counts = await self._outbound_queue_repository.count_by_priority_and_status(
            priorities={0, 1},
            statuses={"pending", "failed"},
        )
        crm_sync_errors = await self._crm_outbox_repository.count_dlq_items()
        total_messages_last_24h = await self._conversation_event_repository.count_since(
            datetime.now(UTC) - timedelta(hours=24)
        )

        return {
            "active_sessions": active_sessions,
            "pending_handoffs": pending_handoffs,
            "outbound_queue_stats": {
                "P0": {
                    "pending": outbound_counts.get(0, {}).get("pending", 0),
                    "failed": outbound_counts.get(0, {}).get("failed", 0),
                },
                "P1": {
                    "pending": outbound_counts.get(1, {}).get("pending", 0),
                    "failed": outbound_counts.get(1, {}).get("failed", 0),
                },
            },
            "crm_sync_errors": crm_sync_errors,
            "total_messages_last_24h": total_messages_last_24h,
        }
