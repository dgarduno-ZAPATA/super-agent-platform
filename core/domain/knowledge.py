from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    source_id: str
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    source_id: str
    title: str
    source_type: str
    metadata: dict[str, object] = field(default_factory=dict)
