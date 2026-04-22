from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adapters.llm.vertex_embedding_adapter import VertexEmbeddingAdapter
from adapters.storage.models import KnowledgeChunkModel, KnowledgeSourceModel
from core.domain.knowledge import KnowledgeChunk, KnowledgeSource
from core.ports.knowledge_provider import KnowledgeProvider
from core.ports.llm_provider import LLMProvider


class PgVectorKnowledgeAdapter(KnowledgeProvider):
    def __init__(
        self,
        llm_provider: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_adapter: VertexEmbeddingAdapter | None = None,
        similarity_threshold: float = 0.7,
    ) -> None:
        self._llm_provider = llm_provider
        self._session_factory = session_factory
        self._embedding_adapter = embedding_adapter
        self._similarity_threshold = similarity_threshold

    async def index_document(
        self, source_id: str, content: str, metadata: dict[str, object]
    ) -> None:
        chunks = self._chunk_content(content)
        if not chunks:
            return

        vectors = await self._embed_documents(chunks)
        if len(vectors) != len(chunks):
            raise ValueError("embedding response count does not match generated chunks")

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source_version = str(metadata.get("version") or "v1")
        indexed_at = datetime.now(UTC)

        async with self._session_factory() as session, session.begin():
            source = await self._get_source_by_key(session, source_id)
            if source is None:
                source = KnowledgeSourceModel(
                    id=uuid4(),
                    source_key=source_id,
                    version=source_version,
                    content_hash=content_hash,
                    indexed_at=indexed_at,
                    status="indexed",
                    metadata_json=metadata,
                )
                session.add(source)
                await session.flush()
            else:
                source.version = source_version
                source.content_hash = content_hash
                source.indexed_at = indexed_at
                source.status = "indexed"
                source.metadata_json = metadata
                await session.execute(
                    delete(KnowledgeChunkModel).where(KnowledgeChunkModel.source_id == source.id)
                )

            for chunk_index, (chunk_content, vector) in enumerate(
                zip(chunks, vectors, strict=True)
            ):
                session.add(
                    KnowledgeChunkModel(
                        id=uuid4(),
                        source_id=source.id,
                        chunk_index=chunk_index,
                        content=chunk_content,
                        embedding=vector,
                    )
                )

    async def query(
        self, question: str, top_k: int, filters: dict[str, object] | None
    ) -> list[KnowledgeChunk]:
        if top_k <= 0:
            return []

        query_vector = await self._embed_query(question)

        distance_expr = KnowledgeChunkModel.embedding.cosine_distance(query_vector)
        similarity_expr = (1 - distance_expr).label("similarity")
        statement: Select[tuple[KnowledgeChunkModel, KnowledgeSourceModel, float]] = (
            select(KnowledgeChunkModel, KnowledgeSourceModel, similarity_expr)
            .join(KnowledgeSourceModel, KnowledgeSourceModel.id == KnowledgeChunkModel.source_id)
            .where(similarity_expr > self._similarity_threshold)
            .order_by(distance_expr.asc())
            .limit(top_k)
        )
        statement = self._apply_filters(statement, filters)

        async with self._session_factory() as session:
            result = await session.execute(statement)
            rows = result.all()

        chunks: list[KnowledgeChunk] = []
        for chunk_model, source_model, similarity in rows:
            score = float(similarity)
            chunk_metadata = {
                "source_metadata": dict(source_model.metadata_json),
                "chunk_index": chunk_model.chunk_index,
            }
            chunks.append(
                KnowledgeChunk(
                    source_id=source_model.source_key,
                    chunk_id=str(chunk_model.id),
                    content=chunk_model.content,
                    score=score,
                    metadata=chunk_metadata,
                )
            )

        return chunks

    async def delete_source(self, source_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            source = await self._get_source_by_key(session, source_id)
            if source is not None:
                await session.delete(source)

    async def list_sources(self) -> list[KnowledgeSource]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeSourceModel).order_by(KnowledgeSourceModel.indexed_at.desc())
            )
            rows = result.scalars().all()

        sources: list[KnowledgeSource] = []
        for row in rows:
            metadata = dict(row.metadata_json)
            title_value = metadata.get("title")
            source_type_value = metadata.get("source_type")
            sources.append(
                KnowledgeSource(
                    source_id=row.source_key,
                    title=title_value if isinstance(title_value, str) else row.source_key,
                    source_type=(
                        source_type_value if isinstance(source_type_value, str) else "unknown"
                    ),
                    metadata=metadata,
                )
            )
        return sources

    @staticmethod
    def _chunk_content(content: str, max_chars: int = 500) -> list[str]:
        paragraphs = [part.strip() for part in content.splitlines() if part.strip()]
        if not paragraphs:
            return []

        chunks: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) > max_chars:
                chunks.extend(PgVectorKnowledgeAdapter._split_long_paragraph(paragraph, max_chars))
            else:
                chunks.append(paragraph)

        return chunks

    @staticmethod
    def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
        words = paragraph.split()
        if not words:
            return []

        chunks: list[str] = []
        current_words: list[str] = []
        for word in words:
            candidate_words = [*current_words, word]
            candidate = " ".join(candidate_words)
            if len(candidate) <= max_chars:
                current_words = candidate_words
            else:
                if current_words:
                    chunks.append(" ".join(current_words))
                current_words = [word]

        if current_words:
            chunks.append(" ".join(current_words))
        return chunks

    @staticmethod
    async def _get_source_by_key(
        session: AsyncSession, source_key: str
    ) -> KnowledgeSourceModel | None:
        result = await session.execute(
            select(KnowledgeSourceModel).where(KnowledgeSourceModel.source_key == source_key)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _apply_filters(
        statement: Select[tuple[KnowledgeChunkModel, KnowledgeSourceModel, float]],
        filters: dict[str, object] | None,
    ) -> Select[tuple[KnowledgeChunkModel, KnowledgeSourceModel, float]]:
        if filters is None:
            return statement

        source_id = filters.get("source_id")
        if isinstance(source_id, str) and source_id.strip():
            statement = statement.where(KnowledgeSourceModel.source_key == source_id)

        source_type = filters.get("source_type")
        if isinstance(source_type, str) and source_type.strip():
            statement = statement.where(
                KnowledgeSourceModel.metadata_json["source_type"].astext == source_type
            )

        return statement

    async def _embed_documents(self, chunks: list[str]) -> list[list[float]]:
        if self._embedding_adapter is None:
            return await self._llm_provider.embed(chunks)
        vectors: list[list[float]] = []
        for chunk in chunks:
            vectors.append(await self._embedding_adapter.embed(chunk))
        return vectors

    async def _embed_query(self, question: str) -> list[float]:
        if self._embedding_adapter is None:
            query_vectors = await self._llm_provider.embed([question])
            if not query_vectors:
                raise RuntimeError("missing query embedding")
            return query_vectors[0]
        return await self._embedding_adapter.embed_query(question)
