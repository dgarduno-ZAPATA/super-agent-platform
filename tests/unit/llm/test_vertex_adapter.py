from __future__ import annotations

from adapters.llm.vertex_adapter import VertexLLMAdapter
from core.domain.messaging import ChatMessage


def test_map_tool_message_omits_function_response_id() -> None:
    message = ChatMessage(
        role="tool",
        name="inventory_query",
        tool_call_id="call_123",
        content="resultado",
    )

    payload = VertexLLMAdapter._map_message(message)
    function_response = payload["parts"][0]["functionResponse"]

    assert payload["role"] == "user"
    assert function_response["name"] == "inventory_query"
    assert "id" not in function_response
    assert function_response["response"] == {"content": "resultado"}
