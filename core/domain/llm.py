from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    finish_reason: str
    tool_calls: tuple[ToolSchema, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
