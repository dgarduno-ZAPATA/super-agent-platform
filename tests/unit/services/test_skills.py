from __future__ import annotations

from pathlib import Path

import pytest

from core.brand.loader import load_brand
from core.domain.knowledge import KnowledgeChunk
from core.domain.messaging import MessageDeliveryReceipt
from core.services.skills import SkillExecutionContext, SkillRegistry


class FakeKnowledgeProvider:
    async def index_document(
        self, source_id: str, content: str, metadata: dict[str, object]
    ) -> None:
        del source_id
        del content
        del metadata

    async def query(
        self, question: str, top_k: int, filters: dict[str, object] | None
    ) -> list[KnowledgeChunk]:
        del top_k
        del filters
        return [
            KnowledgeChunk(
                source_id="catalogo",
                chunk_id="chunk-1",
                content=f"Resultado para: {question}",
                score=0.91,
                metadata={},
            )
        ]

    async def delete_source(self, source_id: str) -> None:
        del source_id

    async def list_sources(self):
        return []


class FakeMessagingProvider:
    def __init__(self) -> None:
        self.documents: list[dict[str, str]] = []

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        self.documents.append(
            {
                "to": to,
                "document_url": document_url,
                "filename": filename,
                "correlation_id": correlation_id,
            }
        )
        return MessageDeliveryReceipt(
            message_id="doc-1",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        del to
        del text
        del correlation_id
        raise NotImplementedError

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to
        del image_url
        del caption
        del correlation_id
        raise NotImplementedError

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        del to
        del audio_url
        del correlation_id
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        del message_id
        raise NotImplementedError

    def parse_inbound_event(self, raw_payload: dict[str, object]):
        del raw_payload
        raise NotImplementedError


class FakeInventoryProvider:
    def get_products(self) -> list[dict[str, object]]:
        return [
            {
                "sku": "FL-CASCADIA-2020",
                "name": "Freightliner Cascadia 2020",
                "description": "Unidad demo",
                "price": "No disponible",
                "availability": "No disponible",
                "category": "tractocamion",
            }
        ]

    def search_products(self, query: str) -> list[dict[str, object]]:
        if "cascadia" in query.lower():
            return self.get_products()
        return []


@pytest.mark.asyncio
async def test_query_knowledge_base_formats_results() -> None:
    registry = SkillRegistry(
        knowledge_provider=FakeKnowledgeProvider(),
        inventory_provider=FakeInventoryProvider(),
        messaging_provider=FakeMessagingProvider(),
        brand=load_brand(Path("brand")),
    )

    result = await registry.query_knowledge_base("financiamiento")

    assert "Resultados de conocimiento:" in result
    assert "Resultado para: financiamiento" in result


def test_query_inventory_formats_product_data() -> None:
    registry = SkillRegistry(
        knowledge_provider=FakeKnowledgeProvider(),
        inventory_provider=FakeInventoryProvider(),
        messaging_provider=FakeMessagingProvider(),
        brand=load_brand(Path("brand")),
    )

    result = registry.query_inventory("Cascadia")

    assert "Resultados de inventario:" in result
    assert "Freightliner Cascadia 2020" in result
    assert "Precio:" in result
    assert "Disponibilidad:" in result


@pytest.mark.asyncio
async def test_send_document_calls_messaging_provider() -> None:
    messaging = FakeMessagingProvider()
    registry = SkillRegistry(
        knowledge_provider=FakeKnowledgeProvider(),
        inventory_provider=FakeInventoryProvider(),
        messaging_provider=messaging,
        brand=load_brand(Path("brand")),
    )

    response = await registry.send_document(
        document_id="ficha-cascadia.pdf",
        context=SkillExecutionContext(phone="5214421234567", correlation_id="corr-123"),
    )

    assert response == "Documento enviado con exito"
    assert len(messaging.documents) == 1
    assert messaging.documents[0]["to"] == "5214421234567"
