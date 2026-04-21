from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from core.ports.repositories import (
    ConversationEventRepository,
    CRMOutboxRepository,
    LeadProfileRepository,
    OutboundQueueRepository,
    SessionRepository,
)


class DashboardService:
    def __init__(
        self,
        session_repository: SessionRepository,
        lead_profile_repository: LeadProfileRepository,
        conversation_event_repository: ConversationEventRepository,
        outbound_queue_repository: OutboundQueueRepository,
        crm_outbox_repository: CRMOutboxRepository,
    ) -> None:
        self._session_repository = session_repository
        self._lead_profile_repository = lead_profile_repository
        self._conversation_event_repository = conversation_event_repository
        self._outbound_queue_repository = outbound_queue_repository
        self._crm_outbox_repository = crm_outbox_repository

    async def get_operational_metrics(self) -> dict[str, object]:
        now = datetime.now(UTC)
        since_24h = now - timedelta(hours=24)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=UTC)

        active_sessions = await self._session_repository.count_active_since(
            since=since_24h,
            excluded_states={"closed"},
        )
        pending_handoffs = await self._session_repository.count_by_state("handoff_pending")
        sessions_in_handoff = await self._safe_metric(self._session_repository.count_human_control_sessions)
        sessions_by_fsm_state = await self._safe_metric(self._session_repository.count_grouped_by_state)

        total_leads = await self._safe_metric(self._lead_profile_repository.count_total)
        new_leads_today = await self._safe_metric(
            lambda: self._lead_profile_repository.count_created_since(start_of_day)
        )
        leads_by_stage = await self._safe_metric(self._lead_profile_repository.count_grouped_by_stage)

        outbound_counts = await self._outbound_queue_repository.count_by_priority_and_status(
            priorities={0, 1},
            statuses={"pending", "failed"},
        )
        messages_pending = await self._safe_metric(
            lambda: self._outbound_queue_repository.count_by_statuses({"pending", "processing"})
        )

        messages_sent_today = await self._safe_metric(
            lambda: self._conversation_event_repository.count_by_type_since(
                "outbound_message",
                start_of_day,
            )
        )
        handoffs_today = await self._safe_metric(
            lambda: self._conversation_event_repository.count_by_type_since(
                "handoff_requested",
                start_of_day,
            )
        )
        avg_response_time_minutes = await self._safe_metric(
            lambda: self._conversation_event_repository.average_response_time_minutes_since(start_of_day)
        )

        crm_sync_pending = await self._safe_metric(self._crm_outbox_repository.count_pending_items)
        crm_sync_errors = await self._crm_outbox_repository.count_dlq_items()
        total_messages_last_24h = await self._conversation_event_repository.count_since(
            since_24h
        )

        return {
            "active_sessions": active_sessions,
            "sessions_in_handoff": sessions_in_handoff,
            "sessions_by_fsm_state": sessions_by_fsm_state,
            "pending_handoffs": pending_handoffs,
            "total_leads": total_leads,
            "new_leads_today": new_leads_today,
            "leads_by_stage": leads_by_stage,
            "messages_sent_today": messages_sent_today,
            "messages_pending": messages_pending,
            "crm_sync_pending": crm_sync_pending,
            "crm_sync_dlq": crm_sync_errors,
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
            "handoffs_today": handoffs_today,
            "avg_response_time_minutes": avg_response_time_minutes,
        }

    @staticmethod
    async def _safe_metric(metric_fn: Callable[[], Awaitable[Any]]) -> Any | None:
        try:
            return await metric_fn()
        except (AttributeError, NotImplementedError):
            return None
