from __future__ import annotations

from pathlib import Path

import structlog

from adapters.llm.vertex_embedding_adapter import VertexEmbeddingAdapter
from adapters.storage.repositories.knowledge_repo import PostgresKnowledgeRepository
from core.services.document_chunker import DocumentChunker

logger = structlog.get_logger("super_agent_platform.core.services.knowledge_ingestion_service")


class KnowledgeIngestionService:
    def __init__(
        self,
        chunker: DocumentChunker,
        embedding_adapter: VertexEmbeddingAdapter,
        knowledge_repo: PostgresKnowledgeRepository,
    ) -> None:
        self._chunker = chunker
        self._embedding_adapter = embedding_adapter
        self._knowledge_repo = knowledge_repo

    async def ingest_file(
        self,
        file_bytes: bytes,
        filename: str,
        source_label: str,
    ) -> dict[str, object]:
        extension = Path(filename).suffix.lower()
        chunks = self._extract_chunks(
            file_bytes=file_bytes,
            extension=extension,
            source_label=source_label,
        )
        if not chunks:
            return {"chunks_created": 0, "source_label": source_label}

        full_text = "\n\n".join(str(chunk["text"]) for chunk in chunks)
        source_type = self._resolve_source_type(extension)
        source_id = await self._knowledge_repo.upsert_source(
            source_label=source_label,
            source_type=source_type,
            full_text=full_text,
        )

        indexed_chunks: list[dict[str, object]] = []
        for chunk in chunks:
            embedding = await self._embedding_adapter.embed(str(chunk["text"]))
            indexed_chunks.append({**chunk, "embedding": embedding})

        created = await self._knowledge_repo.replace_chunks(
            source_id=source_id, chunks=indexed_chunks
        )
        logger.info(
            "knowledge_source_ingested",
            source_label=source_label,
            filename=filename,
            chunks_created=created,
        )
        return {"chunks_created": created, "source_label": source_label}

    async def delete_source(self, source_label: str) -> int:
        deleted = await self._knowledge_repo.delete_source(source_label)
        logger.info("knowledge_source_deleted", source_label=source_label, chunks_deleted=deleted)
        return deleted

    async def reindex_source(self, source_label: str) -> dict[str, object]:
        chunks = await self._knowledge_repo.list_chunks_by_source(source_label)
        if not chunks:
            return {"source_label": source_label, "chunks_reindexed": 0}

        full_text = "\n\n".join(content for _, content in chunks)
        source_id = await self._knowledge_repo.upsert_source(
            source_label=source_label,
            source_type="reindexed",
            full_text=full_text,
        )
        reindexed_chunks: list[dict[str, object]] = []
        total = len(chunks)
        for chunk_index, content in chunks:
            embedding = await self._embedding_adapter.embed(content)
            reindexed_chunks.append(
                {
                    "text": content,
                    "source": source_label,
                    "chunk_index": chunk_index,
                    "total_chunks": total,
                    "embedding": embedding,
                }
            )
        replaced = await self._knowledge_repo.replace_chunks(
            source_id=source_id, chunks=reindexed_chunks
        )
        logger.info(
            "knowledge_source_reindexed", source_label=source_label, chunks_reindexed=replaced
        )
        return {"source_label": source_label, "chunks_reindexed": replaced}

    def _extract_chunks(
        self,
        file_bytes: bytes,
        extension: str,
        source_label: str,
    ) -> list[dict[str, object]]:
        if extension == ".pdf":
            return self._chunker.chunk_pdf(file_bytes, source_name=source_label)
        if extension == ".md":
            return self._chunker.chunk_markdown(
                file_bytes.decode("utf-8", errors="ignore"),
                source_name=source_label,
            )
        if extension == ".txt":
            return self._chunker.chunk_plain_text(
                file_bytes.decode("utf-8", errors="ignore"),
                source_name=source_label,
            )
        if extension == ".docx":
            return self._chunker.chunk_docx(file_bytes, source_name=source_label)
        raise ValueError(f"unsupported_file_type:{extension}")

    @staticmethod
    def _resolve_source_type(extension: str) -> str:
        mapping = {
            ".pdf": "pdf",
            ".md": "markdown",
            ".txt": "text",
            ".docx": "docx",
        }
        return mapping.get(extension, "unknown")
