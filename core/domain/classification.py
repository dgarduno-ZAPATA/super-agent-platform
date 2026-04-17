from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class MessageClassification:
    intent: Literal[
        "conversation",
        "opt_out",
        "handoff_request",
        "campaign_reply",
        "unsupported",
    ]
    confidence: float
    fsm_event: str
    metadata: dict[str, object] = field(default_factory=dict)
