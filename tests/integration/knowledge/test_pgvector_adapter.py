from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adapters.knowledge.pgvector_adapter import PgVectorKnowledgeAdapter
from adapters.storage.db import get_session_factory, session_scope
from core.domain.llm import LLMResponse, ToolSchema
from core.domain.messaging import ChatMessage
from tests.integration.knowledge.conftest import run_async


class FakeLLMProvider:
    async def complete(
        self,
        messages: list[ChatMessage],
        system: str,
        tools: list[ToolSchema] | None,
        temperature: float,
    ) -> LLMResponse:
        del messages
        del system
        del tools
        del temperature
        raise NotImplementedError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text_value in texts:
            lowered = text_value.lower()
            if "camion rojo" in lowered or "rojo" in lowered:
                vectors.append([1.0] + [0.0] * 767)
            elif "camion azul" in lowered or "azul" in lowered:
                vectors.append([0.0, 1.0] + [0.0] * 766)
            else:
                vectors.append([0.2] + [0.0] * 767)
        return vectors

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        del audio_bytes
        del mime_type
        raise NotImplementedError


def _clean_knowledge_tables() -> None:
    async def _delete_rows() -> None:
        async with session_scope() as session:
            await session.execute(text("DELETE FROM knowledge_chunks"))
            await session.execute(text("DELETE FROM knowledge_sources"))

    run_async(_delete_rows())


def _get_session_factory_sync() -> async_sessionmaker[AsyncSession]:
    return run_async(get_session_factory())


def test_index_document_persists_source_and_chunks() -> None:
    _clean_knowledge_tables()
    adapter = PgVectorKnowledgeAdapter(
        llm_provider=FakeLLMProvider(),
        session_factory=_get_session_factory_sync(),
    )
    content = (
        "Camion rojo con excelente rendimiento para rutas largas.\n\n"
        "Camion azul ideal para operacion urbana."
    )

    run_async(
        adapter.index_document(
            source_id="catalogo-camiones",
            content=content,
            metadata={"title": "Catalogo", "source_type": "catalog"},
        )
    )

    async def _counts() -> tuple[int, int]:
        async with session_scope() as session:
            source_result = await session.execute(text("SELECT COUNT(*) FROM knowledge_sources"))
            chunk_result = await session.execute(text("SELECT COUNT(*) FROM knowledge_chunks"))
            return int(source_result.scalar_one()), int(chunk_result.scalar_one())

    source_count, chunk_count = run_async(_counts())

    assert source_count == 1
    assert chunk_count >= 2


def test_query_returns_most_similar_chunk_first() -> None:
    _clean_knowledge_tables()
    adapter = PgVectorKnowledgeAdapter(
        llm_provider=FakeLLMProvider(),
        session_factory=_get_session_factory_sync(),
    )
    content = (
        "Camion rojo con excelente rendimiento para rutas largas.\n\n"
        "Camion azul ideal para operacion urbana."
    )
    run_async(
        adapter.index_document(
            source_id="catalogo-camiones",
            content=content,
            metadata={"title": "Catalogo", "source_type": "catalog"},
        )
    )

    results = run_async(adapter.query(question="Necesito opciones en rojo", top_k=2, filters=None))

    assert len(results) >= 1
    assert "camion rojo" in results[0].content.lower()
