from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import structlog

from core.brand.schema import Brand
from core.domain.llm import ToolCall, ToolResult, ToolSchema
from core.ports.inventory_provider import InventoryProvider
from core.ports.knowledge_provider import KnowledgeProvider
from core.ports.messaging_provider import MessagingProvider

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SkillExecutionContext:
    phone: str
    correlation_id: str


class SkillRegistry:
    _photo_cursor_by_phone: dict[str, dict[str, object]] = {}

    def __init__(
        self,
        knowledge_provider: KnowledgeProvider,
        inventory_provider: InventoryProvider,
        messaging_provider: MessagingProvider,
        brand: Brand,
    ) -> None:
        self._knowledge_provider = knowledge_provider
        self._inventory_provider = inventory_provider
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
                        },
                        "location": {
                            "type": "string",
                            "description": (
                                "Sucursal o ciudad a filtrar, ej: Tampico, Querétaro, Monterrey"
                            ),
                        },
                    },
                    "required": ["product_name"],
                },
            ),
            ToolSchema(
                name="send_inventory_photos",
                description=(
                    "Envia fotos reales de inventario al cliente por WhatsApp para una unidad "
                    "especifica (marca/modelo/SKU)."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Nombre, modelo o SKU de la unidad para buscar fotos.",
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
                product_name = self._get_optional_string(call.arguments, "product_name")
                location = self._get_optional_string(call.arguments, "location")
                content = self.query_inventory(product_name=product_name, location=location)
                return ToolResult(tool_call_id=call.id, name=call.name, content=content)

            if call.name == "send_document":
                document_id = self._get_required_string(call.arguments, "document_id")
                content = await self.send_document(
                    document_id=document_id,
                    context=context,
                )
                return ToolResult(tool_call_id=call.id, name=call.name, content=content)

            if call.name == "send_inventory_photos":
                product_name = self._get_required_string(call.arguments, "product_name")
                content = await self.send_inventory_photos(
                    product_name=product_name,
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
            top_k=5,
            filters=None,
        )
        if not chunks:
            return "No se encontraron resultados en la base de conocimiento."

        lines = ["Resultados de conocimiento relevantes:"]
        for index, chunk in enumerate(chunks, start=1):
            lines.append(
                f"{index}. Fuente: {chunk.source_id} | similitud={chunk.score:.3f} | "
                f"{chunk.content}"
            )
        return "\n".join(lines)

    def query_inventory(
        self,
        product_name: str | None = None,
        location: str | None = None,
        max_results: int = 20,
    ) -> str:
        query_term = (product_name or "").strip()
        location_term = (location or "").strip()
        filters: dict[str, object] = {}
        if location_term:
            filters["location"] = location_term
        logger.debug(
            "inventory_query_started",
            # TODO: lead_id no disponible en este scope (Sprint E refactor)
            lead_id=None,
            # TODO: correlation_id no disponible en este scope (Sprint E refactor)
            correlation_id=None,
            evento="inventory_query_started",
            resultado="ok",
            filters=filters if filters else None,
        )
        try:
            matches = (
                self._inventory_provider.search_products(product_name)
                if product_name and product_name.strip()
                else self._inventory_provider.get_products()
            )
        except Exception:
            logger.error(
                "inventory_query_error",
                # TODO: lead_id no disponible en este scope (Sprint E refactor)
                lead_id=None,
                # TODO: correlation_id no disponible en este scope (Sprint E refactor)
                correlation_id=None,
                evento="inventory_query_error",
                resultado="error",
                exc_info=True,
            )
            raise
        if location_term:
            matches = self._filter_products_by_location(matches, location_term)
        fallback_used = bool(matches) and all(
            not isinstance(product.get("metadata"), dict) for product in matches
        )
        if fallback_used or not matches:
            logger.warning(
                "inventory_query_empty",
                # TODO: lead_id no disponible en este scope (Sprint E refactor)
                lead_id=None,
                # TODO: correlation_id no disponible en este scope (Sprint E refactor)
                correlation_id=None,
                evento="inventory_query_empty",
                resultado="fallback",
            )
        else:
            logger.debug(
                "inventory_query_ok",
                # TODO: lead_id no disponible en este scope (Sprint E refactor)
                lead_id=None,
                # TODO: correlation_id no disponible en este scope (Sprint E refactor)
                correlation_id=None,
                evento="inventory_query_ok",
                resultado="ok",
                total_units=len(matches),
            )
        if not matches:
            if query_term and location_term:
                return (
                    f"No se encontraron productos para '{query_term}' "
                    f"en la ubicación '{location_term}'."
                )
            if query_term:
                return f"No se encontraron productos para '{query_term}'."
            if location_term:
                return f"No se encontraron productos para la ubicación '{location_term}'."
            return "No hay productos disponibles en inventario."

        lines = ["Resultados de inventario:"]
        display_matches = matches[:max_results]
        for index, product in enumerate(display_matches, start=1):
            sku = str(product.get("sku", "N/A"))
            name = str(product.get("name", "Sin nombre"))
            price = str(product.get("price", "No disponible"))
            availability = str(product.get("availability", "No disponible"))
            description = str(product.get("description", "Sin descripcion"))
            media_urls = self._extract_media_urls(product)
            photo_info = (
                f"Fotos: {', '.join(media_urls[:2])}" if media_urls else "Fotos: No disponibles"
            )
            lines.append(
                f"{index}. {name} (SKU: {sku}) | "
                f"Precio: {price} | Disponibilidad: {availability} | "
                f"Descripcion: {description} | {photo_info}"
            )
        if len(matches) > len(display_matches):
            lines.append(
                f"Se muestran {len(display_matches)} de {len(matches)} resultados totales."
            )
        return "\n".join(lines)

    @staticmethod
    def _filter_products_by_location(
        products: list[dict[str, object]],
        location: str,
    ) -> list[dict[str, object]]:
        normalized_location = location.casefold().strip()
        if not normalized_location:
            return products

        filtered: list[dict[str, object]] = []
        for product in products:
            metadata = product.get("metadata")
            if not isinstance(metadata, dict):
                continue
            location_value = str(metadata.get("location", "")).casefold()
            physical_location_value = str(metadata.get("physical_location", "")).casefold()
            if (
                normalized_location in location_value
                or normalized_location in physical_location_value
            ):
                filtered.append(product)
        return filtered

    async def send_inventory_photos(
        self,
        product_name: str,
        context: SkillExecutionContext,
        max_images_per_message: int = 5,
    ) -> str:
        query = product_name.strip()
        if not query:
            return "Necesito el nombre o SKU de la unidad para enviarte fotos."

        if self._is_follow_up_photo_query(query):
            follow_up_response = await self._send_follow_up_photos(
                phone=context.phone,
                correlation_id=context.correlation_id,
                max_images=max_images_per_message,
            )
            if follow_up_response is not None:
                return follow_up_response

        matches = self._inventory_provider.search_products(query)
        if not matches:
            logger.info("inventory_photos_not_found", query=query, phone=context.phone)
            return f"No encontre unidades para '{query}'."

        selected_product: dict[str, object] | None = None
        selected_media_urls: list[str] = []
        for product in matches:
            media_urls = self._extract_media_urls(product)
            if media_urls:
                selected_product = product
                selected_media_urls = media_urls
                break

        if selected_product is None:
            return (
                f"Encontre unidades para '{query}', pero no tienen URLs de fotos disponibles "
                "en inventario."
            )

        product_name_text = str(selected_product.get("name", "Unidad"))
        sent_images = await self._send_image_batch(
            phone=context.phone,
            correlation_id=context.correlation_id,
            unit_name=product_name_text,
            urls=selected_media_urls,
            start_index=0,
            max_images=max_images_per_message,
        )

        self._photo_cursor_by_phone[context.phone] = {
            "unit_name": product_name_text,
            "urls": selected_media_urls,
            "next_index": sent_images,
        }

        logger.info(
            "inventory_photos_sent",
            query=query,
            phone=context.phone,
            sent_images=sent_images,
            sent_units=[product_name_text],
            total_available=len(selected_media_urls),
        )
        if sent_images == 0:
            return (
                f"Encontre unidades para '{query}', pero no tienen URLs de fotos disponibles "
                "en inventario."
            )
        return f"Listo, te envie {sent_images} fotos de inventario."

    async def send_document(self, document_id: str, context: SkillExecutionContext) -> str:
        document_url = self._resolve_document_url(document_id)
        if document_url is None:
            return "La ficha técnica de esa unidad no está disponible en este momento."
        filename = Path(document_id).name if Path(document_id).name else "documento.pdf"
        await self._messaging_provider.send_document(
            to=context.phone,
            document_url=document_url,
            filename=filename,
            correlation_id=context.correlation_id,
        )
        return "Documento enviado con exito"

    @staticmethod
    def _get_required_string(arguments: dict[str, object], key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"argumento requerido faltante: {key}")
        return value.strip()

    @staticmethod
    def _get_optional_string(arguments: dict[str, object], key: str) -> str | None:
        value = arguments.get(key)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @staticmethod
    def _resolve_document_url(document_id: str) -> str | None:
        normalized = document_id.strip()
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
        return None

    @staticmethod
    def _extract_media_urls(product: dict[str, object]) -> list[str]:
        urls: list[str] = []
        metadata = product.get("metadata")
        if isinstance(metadata, dict):
            image_urls = metadata.get("image_urls")
            if isinstance(image_urls, list):
                for value in image_urls:
                    if isinstance(value, str) and SkillRegistry._is_http_url(value):
                        urls.append(value.strip())
            image_url = metadata.get("image_url")
            if isinstance(image_url, str) and SkillRegistry._is_http_url(image_url):
                urls.append(image_url.strip())

        media_urls = product.get("media_urls")
        if isinstance(media_urls, list):
            for value in media_urls:
                if isinstance(value, str) and SkillRegistry._is_http_url(value):
                    urls.append(value.strip())

        deduped: list[str] = []
        for url in urls:
            if url not in deduped:
                deduped.append(url)
        return deduped

    @staticmethod
    def _is_http_url(value: str) -> bool:
        return bool(re.match(r"^https?://", value.strip(), flags=re.IGNORECASE))

    async def _send_follow_up_photos(
        self,
        phone: str,
        correlation_id: str,
        max_images: int,
    ) -> str | None:
        cursor = self._photo_cursor_by_phone.get(phone)
        if not isinstance(cursor, dict):
            return None

        urls_raw = cursor.get("urls")
        unit_name_raw = cursor.get("unit_name")
        next_index_raw = cursor.get("next_index")
        if not isinstance(urls_raw, list) or not isinstance(unit_name_raw, str):
            return None
        urls = [value for value in urls_raw if isinstance(value, str) and self._is_http_url(value)]
        if not urls:
            return None
        next_index = int(next_index_raw) if isinstance(next_index_raw, int) else 0

        if next_index >= len(urls):
            return "Ya te comparti todas las fotos disponibles de esa unidad."

        sent_images = await self._send_image_batch(
            phone=phone,
            correlation_id=correlation_id,
            unit_name=unit_name_raw,
            urls=urls,
            start_index=next_index,
            max_images=max_images,
        )
        self._photo_cursor_by_phone[phone] = {
            "unit_name": unit_name_raw,
            "urls": urls,
            "next_index": next_index + sent_images,
        }
        if sent_images == 0:
            return "No pude enviar mas fotos en este momento."
        return f"Listo, te envie {sent_images} fotos adicionales."

    async def _send_image_batch(
        self,
        phone: str,
        correlation_id: str,
        unit_name: str,
        urls: list[str],
        start_index: int,
        max_images: int,
    ) -> int:
        sent_images = 0
        slice_end = min(len(urls), max(0, start_index) + max(1, max_images))
        for index in range(start_index, slice_end):
            image_url = urls[index]
            caption = f"Fotos de {unit_name}" if sent_images == 0 else None
            await self._messaging_provider.send_image(
                to=phone,
                image_url=image_url,
                caption=caption,
                correlation_id=correlation_id,
            )
            sent_images += 1
        return sent_images

    @staticmethod
    def _is_follow_up_photo_query(query: str) -> bool:
        normalized = query.strip().lower()
        if not normalized:
            return False

        direct_phrases = {
            "fotos",
            "foto",
            "mas fotos",
            "más fotos",
            "tienes fotos",
            "tienes imagenes",
            "tienes imágenes",
            "manda fotos",
            "mandame fotos",
            "mándame fotos",
        }
        if normalized in direct_phrases:
            return True

        tokens = re.findall(r"[a-z0-9áéíóúñ]+", normalized, flags=re.IGNORECASE)
        has_photo_word = any(
            token in {"foto", "fotos", "imagen", "imagenes", "imágenes"} for token in tokens
        )
        has_follow_word = any(
            token in {"mas", "más", "manda", "mandame", "mándame", "tienes"} for token in tokens
        )
        return has_photo_word and has_follow_word and len(tokens) <= 5
