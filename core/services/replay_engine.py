from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from core.domain.conversation_event import ConversationEvent
from core.domain.lead import LeadProfile
from core.domain.session import Session
from core.fsm.actions import ActionRegistry
from core.fsm.engine import FSMEngine
from core.fsm.schema import FSMConfig
from core.ports.repositories import (
    ConversationEventRepository,
    LeadProfileRepository,
    SessionRepository,
)


@dataclass(frozen=True, slots=True)
class ReplayConversationData:
    lead: LeadProfile
    session: Session | None
    events: list[ConversationEvent]


class ReplayEngine:
    def __init__(
        self,
        lead_profile_repository: LeadProfileRepository,
        session_repository: SessionRepository,
        event_repository: ConversationEventRepository,
        fsm_config: FSMConfig,
        handoff_keywords: list[str] | None = None,
        opt_out_keywords: list[str] | None = None,
    ) -> None:
        self._lead_profile_repository = lead_profile_repository
        self._session_repository = session_repository
        self._event_repository = event_repository
        self._fsm_config = fsm_config
        self._handoff_keywords = [
            item.strip().casefold() for item in (handoff_keywords or []) if item.strip()
        ]
        self._opt_out_keywords = [
            item.strip().casefold() for item in (opt_out_keywords or []) if item.strip()
        ]

    async def load_conversation(self, lead_id: UUID) -> ReplayConversationData:
        lead = await self._lead_profile_repository.get_by_id(lead_id)
        if lead is None:
            raise ValueError(f"lead not found: {lead_id}")
        session = await self._session_repository.get_by_lead_id(lead_id)
        events = await self._event_repository.list_by_lead_id(lead_id, limit=2000)
        if not events and session is not None:
            conversation_id = uuid5(NAMESPACE_URL, f"whatsapp:{lead.phone}")
            events = await self._event_repository.list_by_conversation(
                conversation_id=conversation_id,
                limit=2000,
            )
        return ReplayConversationData(lead=lead, session=session, events=events)

    async def build_trace(self, lead_id: UUID) -> dict[str, object]:
        data = await self.load_conversation(lead_id)
        replay = await self.replay_conversation(lead_id=lead_id, dry_run=True)
        transitions = cast(list[dict[str, object]], replay["transitions"])
        transition_by_event = {item["event_id"]: item for item in transitions}

        trace_events: list[dict[str, object]] = []
        inbound_count = 0
        outbound_count = 0
        handoff_count = 0
        fsm_transitions = 0

        for event in data.events:
            trace_type = self._map_trace_type(event.event_type)
            direction = self._map_direction(event.event_type)
            content = self._extract_content(event)
            transition = transition_by_event.get(str(event.id))
            if direction == "in":
                inbound_count += 1
            if direction == "out":
                outbound_count += 1
            if trace_type == "handoff" or (
                transition is not None and transition.get("fsm_event") == "handoff_requested"
            ):
                handoff_count += 1
            if transition is not None and transition.get("transition_taken") is True:
                fsm_transitions += 1

            trace_events.append(
                {
                    "event_id": str(event.id),
                    "type": trace_type,
                    "timestamp": event.created_at.isoformat(),
                    "direction": direction,
                    "content": content,
                    "fsm_state_before": transition["state_before"] if transition else None,
                    "fsm_state_after": transition["state_after"] if transition else None,
                    "metadata": dict(event.payload),
                }
            )

        duration_minutes = 0
        if data.events:
            first = data.events[0].created_at
            last = data.events[-1].created_at
            duration_minutes = int((last - first).total_seconds() / 60)

        current_fsm_state = (
            data.session.current_state
            if data.session is not None
            else self._fsm_config.initial_state
        )
        human_in_control = bool(
            data.session is not None
            and (
                data.session.current_state == "handoff_active"
                or data.session.context.get("owner") == "human_agent"
                or self._read_bool(data.session.context.get("human_in_control"))
                or self._read_nested_bool(data.session.context.get("handoff"), "active")
            )
        )

        return {
            "lead_id": str(data.lead.id),
            "phone": data.lead.phone,
            "created_at": data.lead.created_at.isoformat(),
            "current_fsm_state": current_fsm_state,
            "human_in_control": human_in_control,
            "events": trace_events,
            "summary": {
                "total_messages": inbound_count + outbound_count,
                "inbound_count": inbound_count,
                "outbound_count": outbound_count,
                "handoff_count": handoff_count,
                "fsm_transitions": fsm_transitions,
                "duration_minutes": duration_minutes,
            },
        }

    async def replay_conversation(
        self,
        lead_id: UUID,
        until_event_id: UUID | None = None,
        dry_run: bool = True,
    ) -> dict[str, object]:
        data = await self.load_conversation(lead_id)
        action_registry = self._build_noop_action_registry() if dry_run else None
        engine = FSMEngine(
            config=self._fsm_config,
            current_state=self._fsm_config.initial_state,
            action_registry=action_registry,
        )
        context: dict[str, object] = {
            "phone": data.lead.phone,
            "name": data.lead.name,
            "is_silenced": False,
            "opt_out_detected": False,
        }
        transitions: list[dict[str, object]] = []
        for event in data.events:
            fsm_event = self._infer_fsm_event(event)
            if fsm_event is None:
                transitions.append(
                    {
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "timestamp": event.created_at.isoformat(),
                        "fsm_event": None,
                        "state_before": engine.get_current_state(),
                        "state_after": engine.get_current_state(),
                        "actions_executed": [],
                        "transition_taken": False,
                        "no_transition_matched": True,
                    }
                )
            else:
                before = engine.get_current_state()
                if fsm_event == "opt_out_detected":
                    context["opt_out_detected"] = True
                result = await engine.process_event(fsm_event, context)
                context["opt_out_detected"] = False
                transitions.append(
                    {
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "timestamp": event.created_at.isoformat(),
                        "fsm_event": fsm_event,
                        "state_before": before,
                        "state_after": result.new_state,
                        "actions_executed": result.actions_executed,
                        "transition_taken": result.transition_taken,
                        "no_transition_matched": result.no_transition_matched,
                    }
                )

            if until_event_id is not None and event.id == until_event_id:
                break

        return {
            "lead_id": str(data.lead.id),
            "dry_run": dry_run,
            "transitions": transitions,
            "final_state": engine.get_current_state(),
            "events_processed": len(transitions),
        }

    def _infer_fsm_event(self, event: ConversationEvent) -> str | None:
        if event.event_type == "handoff_requested":
            return "handoff_requested"
        if event.event_type in {"system_agent_took_control", "system_agent_released_control"}:
            return "agent_command"
        if event.event_type != "inbound_message":
            return None

        payload_text = event.payload.get("text")
        text = payload_text.strip().casefold() if isinstance(payload_text, str) else ""
        if text:
            if any(keyword in text for keyword in self._opt_out_keywords):
                return "opt_out_detected"
            if any(keyword in text for keyword in self._handoff_keywords):
                return "handoff_requested"
        return "user_message"

    def _build_noop_action_registry(self) -> ActionRegistry:
        action_names: set[str] = set()
        for state in self._fsm_config.states.values():
            action_names.update(state.on_enter)
            action_names.update(state.on_exit)
            for transition in state.allowed_transitions:
                action_names.update(transition.actions)

        async def _noop(_: dict[str, object]) -> None:
            return

        return {name: _noop for name in action_names}

    @staticmethod
    def _map_trace_type(event_type: str) -> str:
        if event_type == "inbound_message":
            return "inbound"
        if event_type == "outbound_message":
            return "outbound"
        if "handoff" in event_type:
            return "handoff"
        if event_type.startswith("system_"):
            return "system"
        if "fsm" in event_type:
            return "fsm_transition"
        return "system"

    @staticmethod
    def _map_direction(event_type: str) -> str:
        if event_type == "inbound_message":
            return "in"
        if event_type == "outbound_message":
            return "out"
        return "internal"

    @staticmethod
    def _extract_content(event: ConversationEvent) -> str:
        for key in ("text", "message", "summary", "note"):
            value = event.payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return event.event_type

    @staticmethod
    def _read_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().casefold() == "true"
        return False

    @staticmethod
    def _read_nested_bool(value: object, key: str) -> bool:
        if isinstance(value, dict):
            return ReplayEngine._read_bool(value.get(key))
        return False
