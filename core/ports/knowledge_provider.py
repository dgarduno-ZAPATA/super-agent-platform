from typing import Protocol

from core.domain.knowledge import KnowledgeChunk, KnowledgeSource


class KnowledgeProvider(Protocol):
    async def index_document(
        self, source_id: str, content: str, metadata: dict[str, object]
    ) -> None:
        """Persist a source document so it becomes available for future semantic retrieval."""

    async def query(
        self, question: str, top_k: int, filters: dict[str, object] | None
    ) -> list[KnowledgeChunk]:
        """Return the most relevant knowledge chunks for a question under optional canonical filters."""

    async def delete_source(self, source_id: str) -> None:
        """Remove all indexed material associated with a canonical source identifier."""

    async def list_sources(self) -> list[KnowledgeSource]:
        """List the currently indexed knowledge sources available to the system."""
