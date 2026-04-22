from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from adapters.storage.db import session_scope
from adapters.storage.models import KnowledgeChunkModel, KnowledgeSourceModel


@dataclass(frozen=True, slots=True)
class SourceStats:
    source_label: str
    chunk_count: int
    indexed_at: datetime | None


@dataclass(frozen=True, slots=True)
class SimilarChunk:
    text: str
    source: str
    similarity: float
    chunk_index: int


class PostgresKnowledgeRepository:
    async def upsert_source(self, source_label: str, source_type: str, full_text: str) -> UUID:
        content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        indexed_at = datetime.now(UTC)
        async with session_scope() as session:
            result = await session.execute(
                select(KnowledgeSourceModel).where(KnowledgeSourceModel.source_key == source_label)
            )
            source = result.scalar_one_or_none()
            if source is None:
                source = KnowledgeSourceModel(
                    id=uuid4(),
                    source_key=source_label,
                    version="v1",
                    content_hash=content_hash,
                    indexed_at=indexed_at,
                    status="indexed",
                    metadata_json={"title": source_label, "source_type": source_type},
                )
                session.add(source)
                await session.flush()
                return source.id

            source.content_hash = content_hash
            source.indexed_at = indexed_at
            source.status = "indexed"
            source.metadata_json = {
                **dict(source.metadata_json),
                "title": source_label,
                "source_type": source_type,
            }
            return source.id

    async def replace_chunks(
        self,
        source_id: UUID,
        chunks: list[dict[str, object]],
    ) -> int:
        async with session_scope() as session:
            await session.execute(delete(KnowledgeChunkModel).where(KnowledgeChunkModel.source_id == source_id))
            for item in chunks:
                content = str(item["text"])
                chunk_index = int(item["chunk_index"])
                embedding = list(item["embedding"])  # type: ignore[arg-type]
                session.add(
                    KnowledgeChunkModel(
                        id=uuid4(),
                        source_id=source_id,
                        chunk_index=chunk_index,
                        content=content,
                        embedding=embedding,
                    )
                )
        return len(chunks)

    async def delete_source(self, source_label: str) -> int:
        async with session_scope() as session:
            source_result = await session.execute(
                select(KnowledgeSourceModel).where(KnowledgeSourceModel.source_key == source_label)
            )
            source = source_result.scalar_one_or_none()
            if source is None:
                return 0
            count_result = await session.execute(
                select(func.count()).select_from(KnowledgeChunkModel).where(
                    KnowledgeChunkModel.source_id == source.id
                )
            )
            chunk_count = int(count_result.scalar_one())
            await session.delete(source)
            return chunk_count

    async def list_sources(self) -> list[SourceStats]:
        async with session_scope() as session:
            statement = (
                select(
                    KnowledgeSourceModel.source_key,
                    func.count(KnowledgeChunkModel.id),
                    KnowledgeSourceModel.indexed_at,
                )
                .outerjoin(KnowledgeChunkModel, KnowledgeChunkModel.source_id == KnowledgeSourceModel.id)
                .group_by(KnowledgeSourceModel.id)
                .order_by(KnowledgeSourceModel.indexed_at.desc().nullslast())
            )
            rows = (await session.execute(statement)).all()

        return [
            SourceStats(
                source_label=str(source_key),
                chunk_count=int(chunk_count),
                indexed_at=indexed_at,
            )
            for source_key, chunk_count, indexed_at in rows
        ]

    async def list_chunks_by_source(self, source_label: str) -> list[tuple[int, str]]:
        async with session_scope() as session:
            source_result = await session.execute(
                select(KnowledgeSourceModel).where(KnowledgeSourceModel.source_key == source_label)
            )
            source = source_result.scalar_one_or_none()
            if source is None:
                return []
            rows = (
                await session.execute(
                    select(KnowledgeChunkModel.chunk_index, KnowledgeChunkModel.content)
                    .where(KnowledgeChunkModel.source_id == source.id)
                    .order_by(KnowledgeChunkModel.chunk_index.asc())
                )
            ).all()
        return [(int(chunk_index), str(content)) for chunk_index, content in rows]

    async def search_similar(
        self,
        query_vector: list[float],
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> list[SimilarChunk]:
        distance_expr = KnowledgeChunkModel.embedding.cosine_distance(query_vector)
        similarity_expr = (1 - distance_expr).label("similarity")
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        KnowledgeChunkModel.content,
                        KnowledgeSourceModel.source_key,
                        similarity_expr,
                        KnowledgeChunkModel.chunk_index,
                    )
                    .join(KnowledgeSourceModel, KnowledgeSourceModel.id == KnowledgeChunkModel.source_id)
                    .where(similarity_expr > min_similarity)
                    .order_by(distance_expr.asc())
                    .limit(limit)
                )
            ).all()

        return [
            SimilarChunk(
                text=str(text),
                source=str(source),
                similarity=float(similarity),
                chunk_index=int(chunk_index),
            )
            for text, source, similarity, chunk_index in rows
        ]
