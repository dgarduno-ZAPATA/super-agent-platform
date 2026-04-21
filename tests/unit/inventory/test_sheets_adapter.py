from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.brand.schema import InventoryColumnsConfig, ProductConfig
from adapters.inventory.sheets_adapter import SheetsInventoryAdapter


def _fallback_products() -> list[ProductConfig]:
    return [
        ProductConfig(
            sku="FL-CASCADIA-2020",
            name="Freightliner Cascadia 2020",
            description="Unidad fallback",
            metadata={"category": "tractocamion"},
        )
    ]


def test_parse_csv_maps_columns_correctly() -> None:
    csv_text = (
        "nombre,descripcion,precio,disponible,categoria,sku\n"
        "Cascadia 2020,Tracto seminuevo,1200000,si,tractocamion,FL-CASCADIA-2020\n"
    )
    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        http_get=lambda _: csv_text,
    )

    products = adapter.get_products()

    assert len(products) == 1
    assert products[0]["name"] == "Cascadia 2020"
    assert products[0]["description"] == "Tracto seminuevo"
    assert products[0]["price"] == "1200000"
    assert products[0]["availability"] == "si"
    assert products[0]["category"] == "tractocamion"
    assert products[0]["sku"] == "FL-CASCADIA-2020"


def test_search_products_filters_by_query() -> None:
    csv_text = (
        "nombre,descripcion,precio,disponible,categoria,sku\n"
        "Cascadia 2020,Tracto seminuevo,1200000,si,tractocamion,FL-CASCADIA-2020\n"
        "M2 Caja Seca,Camion de reparto,750000,si,reparto,M2-BOX-2018\n"
    )
    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        http_get=lambda _: csv_text,
    )

    matches = adapter.search_products("cascadia")

    assert len(matches) == 1
    assert matches[0]["sku"] == "FL-CASCADIA-2020"


def test_fallback_to_yaml_when_no_url() -> None:
    adapter = SheetsInventoryAdapter(
        csv_url=None,
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
    )

    products = adapter.get_products()

    assert len(products) == 1
    assert products[0]["name"] == "Freightliner Cascadia 2020"
    assert products[0]["sku"] == "FL-CASCADIA-2020"


def test_cache_avoids_second_http_request() -> None:
    now = datetime(2026, 4, 21, tzinfo=UTC)
    call_count = 0

    def _http_get(_: str) -> str:
        nonlocal call_count
        call_count += 1
        return (
            "nombre,descripcion,precio,disponible,categoria,sku\n"
            "Cascadia 2020,Tracto seminuevo,1200000,si,tractocamion,FL-CASCADIA-2020\n"
        )

    current = {"value": now}

    def _now() -> datetime:
        return current["value"]

    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        cache_ttl_seconds=300,
        http_get=_http_get,
        now_provider=_now,
    )

    adapter.get_products()
    current["value"] = now + timedelta(seconds=60)
    adapter.get_products()

    assert call_count == 1
