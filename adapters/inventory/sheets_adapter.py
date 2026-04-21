from __future__ import annotations

import csv
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
        http_get: Callable[[str], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._csv_url = (csv_url or "").strip()
        self._inventory_columns = inventory_columns
        self._fallback_products = fallback_products
        self._cache_ttl_seconds = cache_ttl_seconds
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
            products = self._load_from_fallback()
        else:
            try:
                products = self._load_from_sheet()
            except Exception:
                logger.warning(
                    "inventory_sheet_read_failed_using_fallback",
                    inventory_sheet_url=self._csv_url,
                )
                products = self._load_from_fallback()

        self._cached_products = products
        self._cache_expires_at = now + timedelta(seconds=self._cache_ttl_seconds)
        return products

    def search_products(self, query: str) -> list[dict[str, object]]:
        normalized_query = query.strip().casefold()
        products = self.get_products()
        if not normalized_query:
            return products

        filtered: list[dict[str, object]] = []
        for item in products:
            searchable = " ".join(
                [
                    str(item.get("sku", "")),
                    str(item.get("name", "")),
                    str(item.get("description", "")),
                    str(item.get("category", "")),
                ]
            ).casefold()
            if normalized_query in searchable:
                filtered.append(item)
        return filtered

    def _load_from_sheet(self) -> list[dict[str, object]]:
        rows = self._parse_csv_rows(self._http_get(self._csv_url))
        products: list[dict[str, object]] = []
        for row in rows:
            mapped = self._map_row(row)
            if mapped is not None:
                products.append(mapped)
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

    def _map_row(self, row: dict[str, str]) -> dict[str, object] | None:
        name = str(row.get(self._inventory_columns.name, "")).strip()
        if not name:
            return None

        description = str(row.get(self._inventory_columns.description, "")).strip()
        price = str(row.get(self._inventory_columns.price, "")).strip() or "No disponible"
        availability = (
            str(row.get(self._inventory_columns.availability, "")).strip() or "No disponible"
        )
        category = str(row.get(self._inventory_columns.category, "")).strip() or "No disponible"
        sku = str(row.get(self._inventory_columns.sku, "")).strip()
        if not sku:
            sku = f"SHEET-{name.upper().replace(' ', '-')}"

        return {
            "sku": sku,
            "name": name,
            "description": description,
            "price": price,
            "availability": availability,
            "category": category,
        }

    @staticmethod
    def _default_http_get(url: str) -> str:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
        reader = csv.DictReader(StringIO(csv_text))
        return [dict(row) for row in reader]
