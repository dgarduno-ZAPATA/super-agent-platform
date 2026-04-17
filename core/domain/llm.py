from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    finish_reason: str
    tool_calls: tuple[ToolCall, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
