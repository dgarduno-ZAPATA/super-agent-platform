from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MessageKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT = "contact"
    REACTION = "reaction"
    UNSUPPORTED = "unsupported"


class InvalidInboundPayloadError(ValueError):
    pass


class UnsupportedEventTypeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InboundEvent:
    message_id: str
    from_phone: str
    kind: MessageKind
    text: str | None = None
    media_url: str | None = None
    raw_metadata: dict[str, object] = field(default_factory=dict)
    received_at: datetime = field(default_factory=datetime.utcnow)
    sender_id: str = ""
    channel: str = "whatsapp"
    event_type: str = "inbound_message"
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
