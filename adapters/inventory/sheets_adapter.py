from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import StringIO

import httpx
import structlog

from core.brand.schema import InventoryColumnsConfig, ProductConfig
from core.ports.inventory_provider import InventoryProvider

logger = structlog.get_logger("super_agent_platform.adapters.inventory.sheets_adapter")


class SheetsInventoryAdapter(InventoryProvider):
    def __init__(
        self,
        csv_url: str | None,
        inventory_columns: InventoryColumnsConfig,
        fallback_products: list[ProductConfig],
        cache_ttl_seconds: int = 300,
        allow_fallback: bool = False,
        http_get: Callable[[str], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._csv_url = (csv_url or "").strip()
        self._inventory_columns = inventory_columns
        self._fallback_products = fallback_products
        self._cache_ttl_seconds = cache_ttl_seconds
        self._allow_fallback = allow_fallback
        self._http_get = http_get or self._default_http_get
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._cached_products: list[dict[str, object]] = []
        self._cache_expires_at: datetime | None = None

    def get_products(self) -> list[dict[str, object]]:
        now = self._now_provider()
        if self._cache_expires_at is not None and now < self._cache_expires_at:
            return self._cached_products

        products: list[dict[str, object]]
        if not self._csv_url:
            products = self._load_without_sheet()
        else:
            try:
                products = self._load_from_sheet()
            except Exception:
                products = self._load_after_sheet_failure()

        self._cached_products = products
        self._cache_expires_at = now + timedelta(seconds=self._cache_ttl_seconds)
        return products

    def search_products(self, query: str) -> list[dict[str, object]]:
        normalized_query = self._normalize_text(query)
        products = self.get_products()
        if not normalized_query:
            return products

        query_tokens = self._extract_search_tokens(query)
        filtered: list[dict[str, object]] = []
        for item in products:
            brand_model = self._build_brand_model_text(item)
            if self._matches_query(brand_model, normalized_query, query_tokens):
                filtered.append(item)
                continue

            searchable = self._build_searchable_text(item)
            if self._matches_query(searchable, normalized_query, query_tokens):
                filtered.append(item)
        return filtered

    def _load_from_sheet(self) -> list[dict[str, object]]:
        rows = self._parse_csv_rows(self._http_get(self._csv_url))
        products: list[dict[str, object]] = []
        for row in rows:
            mapped = self._map_row(row)
            if mapped is not None:
                products.append(mapped)
        sample_brand_model: list[str] = []
        for product in products[:5]:
            metadata = product.get("metadata")
            if not isinstance(metadata, dict):
                continue
            brand = str(metadata.get("brand", "")).strip()
            model = str(metadata.get("model", "")).strip()
            combined = " ".join(part for part in (brand, model) if part)
            if combined:
                sample_brand_model.append(combined)
        logger.info(
            "inventory_sheet_loaded",
            total_items=len(products),
            sample_brand_model=sample_brand_model,
        )
        return products

    def _load_from_fallback(self) -> list[dict[str, object]]:
        products: list[dict[str, object]] = []
        for item in self._fallback_products:
            products.append(
                {
                    "sku": item.sku,
                    "name": item.name,
                    "description": item.description,
                    "price": item.metadata.get("price", "No disponible"),
                    "availability": item.metadata.get("availability", "No disponible"),
                    "category": item.metadata.get("category", "No disponible"),
                }
            )
        return products

    def _load_without_sheet(self) -> list[dict[str, object]]:
        if self._allow_fallback:
            logger.warning("inventory_sheet_missing_using_fallback")
            return self._load_from_fallback()

        logger.warning("inventory_sheet_missing_no_fallback")
        return []

    def _load_after_sheet_failure(self) -> list[dict[str, object]]:
        if self._allow_fallback:
            logger.warning(
                "inventory_sheet_read_failed_using_fallback",
                inventory_sheet_url=self._csv_url,
            )
            return self._load_from_fallback()

        logger.warning(
            "inventory_sheet_read_failed_no_fallback",
            inventory_sheet_url=self._csv_url,
        )
        return []

    def _map_row(self, row: dict[str, str]) -> dict[str, object] | None:
        sku = self._resolve_sku(row)
        if not sku:
            return None
        brand = self._safe_get_any(row, ["Marca", self._inventory_columns.brand])
        model = self._safe_get_any(row, ["Modelo", self._inventory_columns.name])
        year = self._safe_get_any(row, ["Año", "AÃ±o", self._inventory_columns.year])
        name = " ".join(part for part in (brand, model, year) if part).strip()
        if not name:
            return None

        engine = self._safe_get_any(row, ["Motor", self._inventory_columns.engine])
        transmission = self._safe_get_any(
            row, ["Transmisión", "TransmisiÃ³n", self._inventory_columns.transmission]
        )
        color = self._safe_get(row, self._inventory_columns.color)
        km = self._normalize_km_value(
            self._safe_get_any(row, ["Kilómetros", "KilÃ³metros", self._inventory_columns.km])
        )
        cover_image_url = self._safe_get_any(
            row,
            ["Imagen Portada", self._inventory_columns.image_url],
        )
        full_images_raw = self._safe_get_any(
            row,
            [
                "Imagenes Completas",
                "Imágenes Completas",
                self._inventory_columns.image_urls,
            ],
        )
        media_urls = self._collect_media_urls(
            cover_image_url=cover_image_url,
            full_images_raw=full_images_raw,
        )
        km_value = str(km) if km is not None else "No disponible"
        description = (
            f"Motor: {engine or 'No disponible'} | "
            f"Trans: {transmission or 'No disponible'} | "
            f"Km: {km_value} | "
            f"Color: {color or 'No disponible'}"
        )
        price = self._normalize_price_value(
            self._safe_get_any(
                row,
                [
                    "Precio Sug. de Venta",
                    "Precio Sugerido de Venta",
                    self._inventory_columns.price,
                ],
            )
        )
        category = brand or "No disponible"
        metadata = {
            "brand": brand,
            "model": model,
            "km": km,
            "engine": engine or "",
            "transmission": transmission or "",
            "color": color or "",
            "year": year or "",
            "location": self._safe_get(row, self._inventory_columns.location),
            "physical_location": self._safe_get(row, self._inventory_columns.physical_location),
            "sleeper": self._safe_get(row, self._inventory_columns.sleeper),
            "paso": self._safe_get(row, self._inventory_columns.paso),
            "promotion": self._safe_get(row, self._inventory_columns.promotion),
            "image_url": cover_image_url,
            "image_urls": media_urls,
            "sku_full": self._safe_get(row, self._inventory_columns.sku_full),
        }

        return {
            "sku": sku,
            "name": name,
            "description": description,
            "price": price,
            "availability": "disponible",
            "category": category,
            "media_urls": media_urls,
            "metadata": metadata,
        }

    def _resolve_sku(self, row: dict[str, str]) -> str:
        sku = self._safe_get(row, self._inventory_columns.sku)
        if sku:
            return sku

        sku_full = self._safe_get(row, self._inventory_columns.sku_full)
        if sku_full:
            return sku_full[:17]
        return ""

    @staticmethod
    def _safe_get(row: dict[str, str], column: str) -> str:
        return str(row.get(column, "")).strip()

    def _safe_get_any(self, row: dict[str, str], candidates: list[str]) -> str:
        normalized_map = {self._normalize_text(key): key for key in row}
        for candidate in candidates:
            found_key = normalized_map.get(self._normalize_text(candidate))
            if found_key is None:
                continue
            value = str(row.get(found_key, "")).strip()
            if value:
                return value
        return ""

    def _collect_media_urls(self, cover_image_url: str, full_images_raw: str) -> list[str]:
        urls: list[str] = []
        if cover_image_url and self._looks_like_http_url(cover_image_url):
            urls.append(cover_image_url.strip())

        for url in self._extract_http_urls(full_images_raw):
            if url not in urls:
                urls.append(url)

        return urls

    @staticmethod
    def _extract_http_urls(raw: str) -> list[str]:
        if not raw:
            return []
        # Extract all http(s) URLs even when separated by spaces, commas, or new lines.
        raw_matches = re.findall(r"https?://[^\s,|;]+", raw, flags=re.IGNORECASE)
        urls: list[str] = []
        for candidate in raw_matches:
            cleaned = candidate.strip().rstrip(".,;|)]}>")
            if cleaned and SheetsInventoryAdapter._looks_like_http_url(cleaned):
                urls.append(cleaned)
        return urls

    @staticmethod
    def _looks_like_http_url(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized.startswith("http://") or normalized.startswith("https://")

    def _build_searchable_text(self, item: dict[str, object]) -> str:
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        searchable = " ".join(
            [
                str(item.get("sku", "")),
                str(item.get("name", "")),
                str(item.get("description", "")),
                str(item.get("category", "")),
                str(metadata.get("location", "")),
                str(metadata.get("physical_location", "")),
            ]
        ).casefold()
        return self._normalize_text(searchable)

    def _build_brand_model_text(self, item: dict[str, object]) -> str:
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            return ""
        return self._normalize_text(f"{metadata.get('brand', '')} {metadata.get('model', '')}")

    @staticmethod
    def _matches_query(text: str, normalized_query: str, query_tokens: list[str]) -> bool:
        if not text:
            return False
        if normalized_query in text:
            return True
        return bool(query_tokens) and any(token in text for token in query_tokens)

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
        lowered = without_accents.casefold()
        return re.sub(r"\s+", " ", lowered).strip()

    @staticmethod
    def _extract_search_tokens(query: str) -> list[str]:
        stopwords = {
            "que",
            "tienes",
            "tienen",
            "opciones",
            "de",
            "del",
            "la",
            "el",
            "por",
            "para",
            "quiero",
            "busco",
            "me",
            "interesa",
            "un",
            "una",
            "los",
            "las",
        }
        normalized = SheetsInventoryAdapter._normalize_text(query)
        tokens = re.findall(r"[a-z0-9]+", normalized)
        return [token for token in tokens if len(token) > 2 and token not in stopwords]

    @staticmethod
    def _normalize_price_value(raw_price: str) -> str:
        if not raw_price:
            return "No disponible"

        normalized = re.sub(r"[^0-9.]", "", raw_price)
        if normalized.count(".") > 1:
            parts = normalized.split(".")
            normalized = "".join(parts[:-1]) + "." + parts[-1]

        if not normalized or normalized == ".":
            return "No disponible"

        try:
            return f"{float(normalized):.2f}"
        except ValueError:
            return "No disponible"

    @staticmethod
    def _normalize_km_value(raw_km: str) -> int | None:
        if not raw_km:
            return None
        digits = re.sub(r"[^0-9]", "", raw_km)
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    @staticmethod
    def _default_http_get(url: str) -> str:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
        reader = csv.DictReader(StringIO(csv_text))
        return [dict(row) for row in reader]
