from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from adapters.storage.db import session_scope
from core.config import get_settings
from tests.integration.api.conftest import run_async


def _seed_dashboard_data() -> None:
    async def _insert() -> None:
        now = datetime.now(UTC)
        lead_1 = uuid4()
        lead_2 = uuid4()
        lead_3 = uuid4()
        lead_4 = uuid4()
        lead_5 = uuid4()

        async with session_scope() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO lead_profiles (
                        id, phone, name, source, metadata, created_at, updated_at
                    )
                    VALUES
                        (
                            :lead_1, '5214423000001', 'Lead 1', 'integration',
                            '{}'::jsonb, :now, :now
                        ),
                        (
                            :lead_2, '5214423000002', 'Lead 2', 'integration',
                            '{}'::jsonb, :now, :now
                        ),
                        (
                            :lead_3, '5214423000003', 'Lead 3', 'integration',
                            '{}'::jsonb, :now, :now
                        ),
                        (
                            :lead_4, '5214423000004', 'Lead 4', 'integration',
                            '{}'::jsonb, :now, :now
                        ),
                        (
                            :lead_5, '5214423000005', 'Lead 5', 'integration',
                            '{}'::jsonb, :now, :now
                        )
                    """
                ),
                {
                    "lead_1": lead_1,
                    "lead_2": lead_2,
                    "lead_3": lead_3,
                    "lead_4": lead_4,
                    "lead_5": lead_5,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO sessions (
                        id, lead_id, current_state, context, created_at, updated_at
                    )
                    VALUES
                        (:session_1, :lead_1, 'greeting', '{}'::jsonb, :now, :now),
                        (:session_2, :lead_2, 'handoff_pending', '{}'::jsonb, :now, :now),
                        (:session_3, :lead_3, 'idle', '{}'::jsonb, :now, :now),
                        (:session_4, :lead_4, 'closed', '{}'::jsonb, :now, :now),
                        (:session_5, :lead_5, 'qualification', '{}'::jsonb, :now, :now)
                    """
                ),
                {
                    "session_1": uuid4(),
                    "session_2": uuid4(),
                    "session_3": uuid4(),
                    "session_4": uuid4(),
                    "session_5": uuid4(),
                    "lead_1": lead_1,
                    "lead_2": lead_2,
                    "lead_3": lead_3,
                    "lead_4": lead_4,
                    "lead_5": lead_5,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO outbound_queue
                        (
                            id, lead_id, campaign_id, priority, payload,
                            status, scheduled_at, attempts
                        )
                    VALUES
                        (
                            :out_1, :lead_1, NULL, 0, '{"text":"p0 pending"}'::jsonb,
                            'pending', :now, 0
                        ),
                        (
                            :out_2, :lead_2, NULL, 0, '{"text":"p0 failed"}'::jsonb,
                            'failed', :now, 1
                        ),
                        (
                            :out_3, :lead_3, NULL, 1, '{"text":"p1 pending"}'::jsonb,
                            'pending', :now, 0
                        ),
                        (
                            :out_4, :lead_4, NULL, 1, '{"text":"p1 sent"}'::jsonb,
                            'sent', :now, 1
                        )
                    """
                ),
                {
                    "out_1": uuid4(),
                    "out_2": uuid4(),
                    "out_3": uuid4(),
                    "out_4": uuid4(),
                    "lead_1": lead_1,
                    "lead_2": lead_2,
                    "lead_3": lead_3,
                    "lead_4": lead_4,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO crm_dlq (id, original_outbox_id, payload, error, moved_at)
                    VALUES
                        (:dlq_1, :outbox_1, '{}'::jsonb, 'error 1', :now),
                        (:dlq_2, :outbox_2, '{}'::jsonb, 'error 2', :now)
                    """
                ),
                {
                    "dlq_1": uuid4(),
                    "dlq_2": uuid4(),
                    "outbox_1": uuid4(),
                    "outbox_2": uuid4(),
                    "now": now,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO conversation_events
                        (id, conversation_id, lead_id, event_type, payload, created_at)
                    VALUES
                        (:evt_1, :conv_1, :lead_1, 'inbound_message', '{}'::jsonb, :recent_now),
                        (:evt_2, :conv_2, :lead_2, 'inbound_message', '{}'::jsonb, :recent_old),
                        (:evt_3, :conv_3, :lead_3, 'inbound_message', '{}'::jsonb, :too_old)
                    """
                ),
                {
                    "evt_1": uuid4(),
                    "evt_2": uuid4(),
                    "evt_3": uuid4(),
                    "conv_1": uuid4(),
                    "conv_2": uuid4(),
                    "conv_3": uuid4(),
                    "lead_1": lead_1,
                    "lead_2": lead_2,
                    "lead_3": lead_3,
                    "recent_now": now - timedelta(hours=1),
                    "recent_old": now - timedelta(hours=23),
                    "too_old": now - timedelta(hours=30),
                },
            )

    run_async(_insert())


def test_dashboard_stats_endpoint_returns_expected_metrics(client: TestClient) -> None:
    _seed_dashboard_data()
    settings = get_settings()
    token_response = client.post(
        "/api/v1/auth/token",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = token_response.json()["access_token"]

    response = client.get(
        "/api/v1/dashboard/stats",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "active_sessions": 4,
        "sessions_in_handoff": 0,
        "sessions_by_fsm_state": {
            "closed": 1,
            "greeting": 1,
            "handoff_pending": 1,
            "idle": 1,
            "qualification": 1,
        },
        "pending_handoffs": 1,
        "total_leads": 5,
        "new_leads_today": 5,
        "leads_by_stage": {"unknown": 5},
        "messages_sent_today": 0,
        "messages_pending": 2,
        "crm_sync_pending": 0,
        "crm_sync_dlq": 2,
        "outbound_queue_stats": {
            "P0": {"pending": 1, "failed": 1},
            "P1": {"pending": 1, "failed": 0},
        },
        "crm_sync_errors": 2,
        "total_messages_last_24h": 2,
        "handoffs_today": 0,
        "avg_response_time_minutes": None,
        "generated_at": payload["generated_at"],
    }
    datetime.fromisoformat(payload["generated_at"])
