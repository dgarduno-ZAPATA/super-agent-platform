from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.brand.schema import Brand, ProductConfig
from core.domain.llm import ToolCall, ToolResult, ToolSchema
from core.ports.knowledge_provider import KnowledgeProvider
from core.ports.messaging_provider import MessagingProvider


@dataclass(frozen=True, slots=True)
class SkillExecutionContext:
    phone: str
    correlation_id: str


class SkillRegistry:
    def __init__(
        self,
        knowledge_provider: KnowledgeProvider,
        messaging_provider: MessagingProvider,
        brand: Brand,
    ) -> None:
        self._knowledge_provider = knowledge_provider
        self._messaging_provider = messaging_provider
        self._brand = brand

    def get_tool_schemas(self) -> list[ToolSchema]:
        return [
            ToolSchema(
                name="query_knowledge_base",
                description="Busca informacion relevante en la base documental de la marca.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Consulta textual del cliente."}
                    },
                    "required": ["query"],
                },
            ),
            ToolSchema(
                name="query_inventory",
                description="Consulta inventario de productos disponibles de la marca.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Nombre o termino para buscar producto.",
                        }
                    },
                    "required": ["product_name"],
                },
            ),
            ToolSchema(
                name="send_document",
                description="Envia un documento al cliente por el canal de mensajeria.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Identificador o URL del documento.",
                        }
                    },
                    "required": ["document_id"],
                },
            ),
        ]

    async def execute_tool(
        self,
        call: ToolCall,
        context: SkillExecutionContext,
    ) -> ToolResult:
        try:
            if call.name == "query_knowledge_base":
                query = self._get_required_string(call.arguments, "query")
                content = await self.query_knowledge_base(query=query)
                return ToolResult(tool_call_id=call.id, name=call.name, content=content)

            if call.name == "query_inventory":
                product_name = self._get_required_string(call.arguments, "product_name")
                content = self.query_inventory(product_name=product_name)
                return ToolResult(tool_call_id=call.id, name=call.name, content=content)

            if call.name == "send_document":
                document_id = self._get_required_string(call.arguments, "document_id")
                content = await self.send_document(
                    document_id=document_id,
                    context=context,
                )
                return ToolResult(tool_call_id=call.id, name=call.name, content=content)

            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=f"Herramienta desconocida: {call.name}",
                is_error=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=f"Error ejecutando {call.name}: {exc}",
                is_error=True,
            )

    async def query_knowledge_base(self, query: str) -> str:
        chunks = await self._knowledge_provider.query(
            question=query,
            top_k=3,
            filters=None,
        )
        if not chunks:
            return "No se encontraron resultados en la base de conocimiento."

        lines = ["Resultados de conocimiento:"]
        for index, chunk in enumerate(chunks, start=1):
            lines.append(f"{index}. ({chunk.source_id}, score={chunk.score:.3f}) {chunk.content}")
        return "\n".join(lines)

    def query_inventory(self, product_name: str) -> str:
        matches = self._match_products(product_name)
        if not matches:
            return f"No se encontraron productos para '{product_name}'."

        lines = ["Resultados de inventario:"]
        for index, product in enumerate(matches, start=1):
            price = product.metadata.get("price", "No disponible")
            availability = product.metadata.get("availability", "No disponible")
            lines.append(
                f"{index}. {product.name} (SKU: {product.sku}) | "
                f"Precio: {price} | Disponibilidad: {availability} | "
                f"Descripcion: {product.description}"
            )
        return "\n".join(lines)

    async def send_document(self, document_id: str, context: SkillExecutionContext) -> str:
        document_url = self._resolve_document_url(document_id)
        filename = Path(document_id).name if Path(document_id).name else "documento.pdf"
        await self._messaging_provider.send_document(
            to=context.phone,
            document_url=document_url,
            filename=filename,
            correlation_id=context.correlation_id,
        )
        return "Documento enviado con exito"

    def _match_products(self, product_name: str) -> list[ProductConfig]:
        lookup = product_name.lower().strip()
        results: list[ProductConfig] = []
        for product in self._brand.products.products:
            if lookup in product.name.lower() or lookup in product.sku.lower():
                results.append(product)
        return results[:5]

    @staticmethod
    def _get_required_string(arguments: dict[str, object], key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"argumento requerido faltante: {key}")
        return value.strip()

    @staticmethod
    def _resolve_document_url(document_id: str) -> str:
        normalized = document_id.strip()
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
        return f"https://docs.example.com/{normalized}"
