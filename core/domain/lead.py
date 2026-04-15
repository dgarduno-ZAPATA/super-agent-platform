from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Lead:
    external_id: str | None = None
    phone: str = ""
    name: str = ""
    stage: str = ""
    source: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
