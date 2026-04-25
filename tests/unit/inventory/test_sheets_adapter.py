from __future__ import annotations

from datetime import UTC, datetime, timedelta

from adapters.inventory.sheets_adapter import SheetsInventoryAdapter
from core.brand.schema import InventoryColumnsConfig, ProductConfig


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
        "VIN COMPLETO,VIN,Centro,Ubicación Física,Marca,Modelo,Año,Precio Sug. de Venta,"
        "Kilómetros,Motor,Transmisión,Color,Dormitorio,Paso,Promoción,"
        "Imagen Portada,Imagenes Completas\n"
        "3AKJGLD59ESF12345,ESF12345,QUERETARO,PATIO A,Freightliner,Cascadia,2020,"
        '"$1,200,000.00","450,000",Detroit DD15,DT12,Blanco,60,3.58,SIN PROMO,'
        "https://img.example.com/cascadia.jpg,https://img.example.com/cascadia-2.jpg|https://img.example.com/cascadia-3.jpg\n"
    )
    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        allow_fallback=True,
        http_get=lambda _: csv_text,
    )

    products = adapter.get_products()

    assert len(products) == 1
    assert products[0]["name"] == "Freightliner Cascadia 2020"
    assert (
        products[0]["description"]
        == "Motor: Detroit DD15 | Trans: DT12 | Km: 450000 | Color: Blanco"
    )
    assert products[0]["price"] == "1200000.00"
    assert products[0]["availability"] == "disponible"
    assert products[0]["category"] == "Freightliner"
    assert products[0]["sku"] == "ESF12345"
    assert products[0]["metadata"]["km"] == 450000
    assert products[0]["metadata"]["engine"] == "Detroit DD15"
    assert products[0]["metadata"]["image_url"] == "https://img.example.com/cascadia.jpg"
    assert products[0]["media_urls"] == [
        "https://img.example.com/cascadia.jpg",
        "https://img.example.com/cascadia-2.jpg",
        "https://img.example.com/cascadia-3.jpg",
    ]


def test_search_products_filters_by_query() -> None:
    csv_text = (
        "VIN COMPLETO,VIN,Centro,Ubicación Física,Marca,Modelo,Año,Precio Sug. de Venta,"
        "Kilómetros,Motor,Transmisión,Color,Dormitorio,Paso,Promoción,Imagen Portada\n"
        "3AKJGLD59ESF12345,ESF12345,QUERETARO,PATIO A,Freightliner,Cascadia,2020,"
        '"$1,200,000.00","450,000",Detroit DD15,DT12,Blanco,60,3.58,SIN PROMO,'
        "https://img.example.com/cascadia.jpg\n"
        "3ALACWFC4JDLM6789,,LEON,PATIO B,International,LT,2019,980000,320000,Cummins X15,"
        "Eaton Fuller,Rojo,52,3.70,PROMO,https://img.example.com/lt.jpg\n"
    )
    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        allow_fallback=True,
        http_get=lambda _: csv_text,
    )

    matches = adapter.search_products("cascadia")

    assert len(matches) == 1
    assert matches[0]["sku"] == "ESF12345"

    fallback_sku = adapter.search_products("international")[0]["sku"]
    assert fallback_sku == "3ALACWFC4JDLM6789"


def test_search_products_matches_brand_and_model_columns_for_kenworth() -> None:
    csv_text = (
        "VIN COMPLETO,VIN,Centro,Ubicación Física,Marca,Modelo,Año,Precio Sug. de Venta,"
        "Kilómetros,Motor,Transmisión,Color,Dormitorio,Paso,Promoción,Imagen Portada\n"
        "3ALACWFC4JDLM6789,,LEON,PATIO B,KENWORTH,T 680,2021,1980000,320000,Cummins X15,"
        "Eaton Fuller,Rojo,52,3.70,PROMO,https://img.example.com/t680.jpg\n"
    )
    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        allow_fallback=True,
        http_get=lambda _: csv_text,
    )

    matches = adapter.search_products("Que opciones de Kenworth tienes?")

    assert len(matches) == 1
    assert matches[0]["name"] == "KENWORTH T 680 2021"
    assert matches[0]["price"] == "1980000.00"


def test_price_uses_precio_sugerido_de_venta_column() -> None:
    csv_text = (
        "VIN COMPLETO,VIN,Centro,Ubicación Física,Marca,Modelo,Año,Precio Sug. de Venta,"
        "Kilómetros,Motor,Transmisión,Color,Dormitorio,Paso,Promoción,Imagen Portada,Precio Lista\n"
        "3ALACWFC4JDLM6789,,LEON,PATIO B,KENWORTH,T 680,2021,1980000,320000,Cummins X15,"
        "Eaton Fuller,Rojo,52,3.70,PROMO,https://img.example.com/t680.jpg,999999\n"
    )
    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(price="Precio Lista"),
        fallback_products=_fallback_products(),
        allow_fallback=True,
        http_get=lambda _: csv_text,
    )

    products = adapter.get_products()

    assert len(products) == 1
    assert products[0]["price"] == "1980000.00"


def test_parse_imagenes_completas_with_spaces_newlines_and_commas() -> None:
    csv_text = (
        "VIN COMPLETO,VIN,Centro,Ubicación Física,Marca,Modelo,Año,Precio Sug. de Venta,"
        "Kilómetros,Motor,Transmisión,Color,Dormitorio,Paso,Promoción,"
        "Imagen Portada,Imagenes Completas\n"
        "3ALACWFC4JDLM6789,,LEON,PATIO B,KENWORTH,T 680,2021,1980000,320000,Cummins X15,"
        "Eaton Fuller,Rojo,52,3.70,PROMO,https://img.example.com/cover.jpg,"
        '"https://img.example.com/a.jpg https://img.example.com/b.jpg,\nhttps://img.example.com/c.jpg"\n'
    )
    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        allow_fallback=True,
        http_get=lambda _: csv_text,
    )

    products = adapter.get_products()

    assert len(products) == 1
    assert products[0]["media_urls"] == [
        "https://img.example.com/cover.jpg",
        "https://img.example.com/a.jpg",
        "https://img.example.com/b.jpg",
        "https://img.example.com/c.jpg",
    ]


def test_fallback_to_yaml_when_no_url() -> None:
    adapter = SheetsInventoryAdapter(
        csv_url=None,
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        allow_fallback=True,
    )

    products = adapter.get_products()

    assert len(products) == 1
    assert products[0]["name"] == "Freightliner Cascadia 2020"
    assert products[0]["sku"] == "FL-CASCADIA-2020"


def test_no_fallback_returns_empty_when_sheet_missing() -> None:
    adapter = SheetsInventoryAdapter(
        csv_url=None,
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        allow_fallback=False,
    )

    products = adapter.get_products()

    assert products == []


def test_cache_avoids_second_http_request() -> None:
    now = datetime(2026, 4, 21, tzinfo=UTC)
    call_count = 0

    def _http_get(_: str) -> str:
        nonlocal call_count
        call_count += 1
        return (
            "VIN COMPLETO,VIN,Centro,Ubicación Física,Marca,Modelo,Año,Precio Sug. de Venta,"
            "Kilómetros,Motor,Transmisión,Color,Dormitorio,Paso,Promoción,Imagen Portada\n"
            "3AKJGLD59ESF12345,ESF12345,QUERETARO,PATIO A,Freightliner,Cascadia,2020,"
            '"$1,200,000.00","450,000",Detroit DD15,DT12,Blanco,60,3.58,SIN PROMO,'
            "https://img.example.com/cascadia.jpg\n"
        )

    current = {"value": now}

    def _now() -> datetime:
        return current["value"]

    adapter = SheetsInventoryAdapter(
        csv_url="https://example.com/inventory.csv",
        inventory_columns=InventoryColumnsConfig(),
        fallback_products=_fallback_products(),
        cache_ttl_seconds=300,
        allow_fallback=True,
        http_get=_http_get,
        now_provider=_now,
    )

    adapter.get_products()
    current["value"] = now + timedelta(seconds=60)
    adapter.get_products()

    assert call_count == 1
