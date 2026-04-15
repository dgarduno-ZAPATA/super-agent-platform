from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class InboundEvent:
    message_id: str
    sender_id: str
    channel: str
    event_type: str
    text: str | None = None
    media_url: str | None = None
    occurred_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MessageDeliveryReceipt:
    message_id: str
    provider: str
    status: str
    correlation_id: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
