from __future__ import annotations

from core.services.conversation_agent import _filter_tool_schemas

MOCK_SCHEMAS = [
    {"function": {"name": "query_inventory"}},
    {"function": {"name": "send_inventory_photos"}},
    {"function": {"name": "query_knowledge_base"}},
]


def test_filter_single_tool() -> None:
    filtered = _filter_tool_schemas(MOCK_SCHEMAS, allowed_tools=["query_inventory"])
    assert len(filtered) == 1
    assert filtered[0]["function"]["name"] == "query_inventory"


def test_filter_empty_list() -> None:
    filtered = _filter_tool_schemas(MOCK_SCHEMAS, allowed_tools=[])
    assert len(filtered) == 0


def test_filter_none_returns_all() -> None:
    filtered = _filter_tool_schemas(MOCK_SCHEMAS, allowed_tools=None)
    assert len(filtered) == 3
    assert filtered == MOCK_SCHEMAS
