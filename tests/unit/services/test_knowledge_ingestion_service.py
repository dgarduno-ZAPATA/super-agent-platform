from __future__ import annotations

import pytest

from core.services.document_chunker import DocumentChunker
from core.services.knowledge_ingestion_service import KnowledgeIngestionService


class FakeEmbeddingAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1] * 768


class FakeKnowledgeRepo:
    def __init__(self) -> None:
        self.source_calls: list[tuple[str, str, str]] = []
        self.chunk_calls: list[tuple[object, list[dict[str, object]]]] = []

    async def upsert_source(self, source_label: str, source_type: str, full_text: str):  # noqa: ANN201
        self.source_calls.append((source_label, source_type, full_text))
        return "source-uuid"

    async def replace_chunks(self, source_id, chunks: list[dict[str, object]]) -> int:  # noqa: ANN001
        self.chunk_calls.append((source_id, chunks))
        return len(chunks)

    async def delete_source(self, source_label: str) -> int:
        del source_label
        return 0

    async def list_chunks_by_source(self, source_label: str) -> list[tuple[int, str]]:
        del source_label
        return []


@pytest.mark.asyncio
async def test_knowledge_ingestion_creates_chunks_with_embeddings() -> None:
    chunker = DocumentChunker()
    embedding_adapter = FakeEmbeddingAdapter()
    repo = FakeKnowledgeRepo()
    service = KnowledgeIngestionService(
        chunker=chunker,
        embedding_adapter=embedding_adapter,  # type: ignore[arg-type]
        knowledge_repo=repo,  # type: ignore[arg-type]
    )

    result = await service.ingest_file(
        file_bytes=("Linea 1\n\nLinea 2\n\nLinea 3" * 100).encode("utf-8"),
        filename="catalogo.txt",
        source_label="Catalogo Q1 2026",
    )

    assert result["source_label"] == "Catalogo Q1 2026"
    assert int(result["chunks_created"]) > 0
    assert len(repo.chunk_calls) == 1
    saved_chunks = repo.chunk_calls[0][1]
    assert len(saved_chunks) == int(result["chunks_created"])
    assert len(embedding_adapter.calls) == len(saved_chunks)


@pytest.mark.asyncio
async def test_knowledge_ingestion_rejects_unsupported_extension() -> None:
    service = KnowledgeIngestionService(
        chunker=DocumentChunker(),
        embedding_adapter=FakeEmbeddingAdapter(),  # type: ignore[arg-type]
        knowledge_repo=FakeKnowledgeRepo(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="unsupported_file_type"):
        await service.ingest_file(
            file_bytes=b"binary",
            filename="archivo.exe",
            source_label="Fuente invalida",
        )


@pytest.mark.asyncio
async def test_knowledge_reindex_source_recomputes_embeddings() -> None:
    repo = FakeKnowledgeRepo()
    embedding_adapter = FakeEmbeddingAdapter()
    service = KnowledgeIngestionService(
        chunker=DocumentChunker(),
        embedding_adapter=embedding_adapter,  # type: ignore[arg-type]
        knowledge_repo=repo,  # type: ignore[arg-type]
    )

    async def _chunks(_: str) -> list[tuple[int, str]]:
        return [(0, "Primer chunk"), (1, "Segundo chunk")]

    repo.list_chunks_by_source = _chunks  # type: ignore[method-assign]
    result = await service.reindex_source("Catalogo Q2")

    assert result["source_label"] == "Catalogo Q2"
    assert result["chunks_reindexed"] == 2
    assert len(embedding_adapter.calls) == 2
