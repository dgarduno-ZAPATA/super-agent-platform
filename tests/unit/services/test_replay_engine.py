from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.session import Session
from core.fsm.schema import FSMConfig
from core.services.replay_engine import ReplayEngine


class FakeLeadRepo:
    def __init__(self, lead: LeadProfile) -> None:
        self.lead = lead

    async def get_by_id(self, lead_id):
        if lead_id == self.lead.id:
            return self.lead
        return None


class FakeSessionRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def get_by_lead_id(self, lead_id):
        if lead_id == self.session.lead_id:
            return self.session
        return None


class FakeEventRepo:
    def __init__(self, events: list[ConversationEvent]) -> None:
        self.events = events

    async def list_by_lead_id(self, lead_id, limit: int = 1000):
        return [item for item in self.events if item.lead_id == lead_id][:limit]

    async def list_by_conversation(self, conversation_id, limit: int = 100):
        return [item for item in self.events if item.conversation_id == conversation_id][:limit]


def _fsm_with_user_transition(action_name: str = "log_transition") -> FSMConfig:
    return FSMConfig.model_validate(
        {
            "initial_state": "idle",
            "states": {
                "idle": {
                    "description": "idle",
                    "on_enter": [],
                    "on_exit": [],
                    "allowed_transitions": [
                        {
                            "target": "greeting",
                            "event": "user_message",
                            "guard": "always",
                            "actions": [action_name],
                        }
                    ],
                },
                "greeting": {
                    "description": "greeting",
                    "on_enter": [],
                    "on_exit": [],
                    "allowed_transitions": [],
                },
            },
        }
    )


def _build_fixture() -> tuple[LeadProfile, Session, list[ConversationEvent]]:
    now = datetime.now(UTC)
    lead = LeadProfile(
        id=uuid4(),
        external_crm_id=None,
        phone="5214421234567",
        name="Lead Replay",
        source="unit",
        attributes={},
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(minutes=30),
    )
    session = Session(
        id=uuid4(),
        lead_id=lead.id,
        current_state="greeting",
        context={},
        created_at=now - timedelta(hours=1),
        updated_at=now,
        last_event_at=now,
    )
    events = [
        ConversationEvent(
            id=uuid4(),
            conversation_id=session.id,
            lead_id=lead.id,
            event_type="inbound_message",
            payload={"text": "Hola"},
            created_at=now - timedelta(minutes=10),
            message_id="wamid-1",
        ),
        ConversationEvent(
            id=uuid4(),
            conversation_id=session.id,
            lead_id=lead.id,
            event_type="outbound_message",
            payload={"text": "Hola, en que te ayudo?"},
            created_at=now - timedelta(minutes=9),
            message_id=None,
        ),
        ConversationEvent(
            id=uuid4(),
            conversation_id=session.id,
            lead_id=lead.id,
            event_type="system_agent_took_control",
            payload={"state": "handoff_active"},
            created_at=now - timedelta(minutes=8),
            message_id=None,
        ),
    ]
    return lead, session, events


@pytest.mark.asyncio
async def test_build_trace_classifies_event_directions() -> None:
    lead, session, events = _build_fixture()
    engine = ReplayEngine(
        lead_profile_repository=FakeLeadRepo(lead),
        session_repository=FakeSessionRepo(session),
        event_repository=FakeEventRepo(events),
        fsm_config=_fsm_with_user_transition(),
        handoff_keywords=["asesor"],
        opt_out_keywords=["stop"],
    )

    trace = await engine.build_trace(lead.id)

    assert trace["events"][0]["direction"] == "in"
    assert trace["events"][1]["direction"] == "out"
    assert trace["events"][2]["direction"] == "internal"


@pytest.mark.asyncio
async def test_replay_returns_fsm_transitions_in_order() -> None:
    lead, session, events = _build_fixture()
    engine = ReplayEngine(
        lead_profile_repository=FakeLeadRepo(lead),
        session_repository=FakeSessionRepo(session),
        event_repository=FakeEventRepo(events),
        fsm_config=_fsm_with_user_transition(),
        handoff_keywords=["asesor"],
        opt_out_keywords=["stop"],
    )

    replay = await engine.replay_conversation(lead.id, dry_run=True)
    transitions = replay["transitions"]

    assert len(transitions) == 3
    assert transitions[0]["state_before"] == "idle"
    assert transitions[0]["state_after"] == "greeting"
    assert transitions[0]["transition_taken"] is True


@pytest.mark.asyncio
async def test_dry_run_does_not_call_real_actions() -> None:
    lead, session, events = _build_fixture()
    engine = ReplayEngine(
        lead_profile_repository=FakeLeadRepo(lead),
        session_repository=FakeSessionRepo(session),
        event_repository=FakeEventRepo(events),
        fsm_config=_fsm_with_user_transition(action_name="custom_action_not_registered"),
        handoff_keywords=["asesor"],
        opt_out_keywords=["stop"],
    )

    replay = await engine.replay_conversation(lead.id, dry_run=True)

    assert replay["events_processed"] == 3
    assert replay["transitions"][0]["actions_executed"] == ["custom_action_not_registered"]
