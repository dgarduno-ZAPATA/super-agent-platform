from __future__ import annotations

import pathlib

import yaml

from core.fsm.tool_policy import FSM_TOOL_POLICY, get_allowed_tools


def test_catalog_navigation_has_inventory_tools() -> None:
    tools = get_allowed_tools("catalog_navigation")
    assert "query_inventory" in tools
    assert "send_inventory_photos" in tools


def test_greeting_has_no_tools() -> None:
    tools = get_allowed_tools("greeting")
    assert tools == []


def test_unknown_state_returns_empty() -> None:
    tools = get_allowed_tools("estado_inexistente")
    assert tools == []


def test_all_states_in_fsm_yaml_covered() -> None:
    fsm = yaml.safe_load(pathlib.Path("brand/fsm.yaml").read_text(encoding="utf-8"))
    states = list((fsm or {}).get("states", {}).keys())
    for state in states:
        assert state in FSM_TOOL_POLICY, f"Estado '{state}' no tiene política de tools"
