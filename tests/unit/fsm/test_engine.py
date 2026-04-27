from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
import yaml

from core.fsm.actions import ActionRegistry
from core.fsm.engine import FSMEngine
from core.fsm.schema import FSMConfig


def _build_engine_config(guard: str = "always") -> FSMConfig:
    return FSMConfig.model_validate(
        {
            "initial_state": "idle",
            "states": {
                "idle": {
                    "description": "Idle state",
                    "allowed_transitions": [
                        {
                            "target": "greeting",
                            "event": "user_message",
                            "guard": guard,
                            "actions": ["transition_action"],
                        }
                    ],
                    "on_enter": [],
                    "on_exit": ["exit_action"],
                },
                "greeting": {
                    "description": "Greeting state",
                    "allowed_transitions": [],
                    "on_enter": ["enter_action"],
                    "on_exit": [],
                },
            },
        }
    )


def _build_action_registry(execution_order: list[str]) -> ActionRegistry:
    async def _record_action(name: str, context: dict[str, object]) -> None:
        del context
        execution_order.append(name)

    def _factory(name: str) -> Callable[[dict[str, object]], Awaitable[None]]:
        async def _action(context: dict[str, object]) -> None:
            await _record_action(name, context)

        return _action

    return {
        "exit_action": _factory("exit_action"),
        "transition_action": _factory("transition_action"),
        "enter_action": _factory("enter_action"),
    }


@pytest.mark.asyncio
async def test_simple_transition_idle_to_greeting() -> None:
    execution_order: list[str] = []
    engine = FSMEngine(
        config=_build_engine_config(),
        current_state="idle",
        action_registry=_build_action_registry(execution_order),
    )

    result = await engine.process_event("user_message", context={})

    assert result.old_state == "idle"
    assert result.new_state == "greeting"
    assert result.transition_taken is True
    assert result.no_transition_matched is False


@pytest.mark.asyncio
async def test_guard_blocks_transition_without_phone() -> None:
    engine = FSMEngine(
        config=_build_engine_config(guard="has_phone_number"),
        current_state="idle",
        action_registry={},
    )

    result = await engine.process_event("user_message", context={})

    assert result.old_state == "idle"
    assert result.new_state == "idle"
    assert result.transition_taken is False
    assert result.no_transition_matched is True


@pytest.mark.asyncio
async def test_guard_allows_transition_with_phone() -> None:
    execution_order: list[str] = []
    engine = FSMEngine(
        config=_build_engine_config(guard="has_phone_number"),
        current_state="idle",
        action_registry=_build_action_registry(execution_order),
    )

    result = await engine.process_event("user_message", context={"phone": "5214421234567"})

    assert result.old_state == "idle"
    assert result.new_state == "greeting"
    assert result.transition_taken is True
    assert result.no_transition_matched is False


@pytest.mark.asyncio
async def test_unknown_event_returns_no_transition_matched() -> None:
    engine = FSMEngine(
        config=_build_engine_config(),
        current_state="idle",
        action_registry={},
    )

    result = await engine.process_event("unknown_event", context={})

    assert result.old_state == "idle"
    assert result.new_state == "idle"
    assert result.no_transition_matched is True


@pytest.mark.asyncio
async def test_actions_execute_in_expected_order() -> None:
    execution_order: list[str] = []
    engine = FSMEngine(
        config=_build_engine_config(),
        current_state="idle",
        action_registry=_build_action_registry(execution_order),
    )

    result = await engine.process_event("user_message", context={})

    assert result.actions_executed == ["exit_action", "transition_action", "enter_action"]
    assert execution_order == ["exit_action", "transition_action", "enter_action"]


@pytest.mark.asyncio
async def test_catalog_navigation_user_message_stays_in_catalog_navigation() -> None:
    payload = yaml.safe_load(Path("brand/fsm.yaml").read_text(encoding="utf-8"))
    config = FSMConfig.model_validate(payload)

    async def _noop(context: dict[str, object]) -> None:
        del context

    action_registry: ActionRegistry = {
        "log_transition": _noop,
        "update_crm_stage": _noop,
        "update_session": _noop,
    }
    engine = FSMEngine(
        config=config,
        current_state="catalog_navigation",
        action_registry=action_registry,
    )

    result = await engine.process_event("user_message", context={"inbound_text": "hola"})

    assert result.old_state == "catalog_navigation"
    assert result.new_state == "catalog_navigation"
    assert result.transition_taken is True
    assert result.no_transition_matched is False
