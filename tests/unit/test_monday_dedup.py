from __future__ import annotations

import pytest

from adapters.crm.monday_adapter import MondayCRMAdapter
from core.domain.lead import Lead


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> MondayCRMAdapter:
    stage_map = {
        "new_lead": "Nuevo",
        "contacted": "Conversando",
        "qualified": "Calificando",
        "quoted": "Listo para Handoff",
        "nurture": "Conversando",
        "handoff": "Listo para Handoff",
        "handoff_done": "Handoff Hecho",
        "won": "Nuevo",
        "lost": "Nuevo",
        "do_not_contact": "Nuevo",
    }
    field_map = {
        "lead_name": "text_mm2kz8c6",
        "phone": "text_mm2k3epp",
        "source": "text_mm2k5g0c",
        "vehicle_interest": "text_mm2ktbs7",
        "city": "text_mm2k4nfy",
        "fsm_state": "color_mm2kvwdj",
    }
    monkeypatch.setattr(MondayCRMAdapter, "_load_stage_map", staticmethod(lambda: stage_map))
    monkeypatch.setattr(MondayCRMAdapter, "_load_field_map", staticmethod(lambda: field_map))
    return MondayCRMAdapter(api_key="test-key", board_id="123")


@pytest.mark.asyncio
async def test_new_lead_creates_item(
    adapter: MondayCRMAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_queries: list[str] = []

    async def _fake_find_item_by_phone(phone: str) -> str | None:
        assert phone == "5214461051272"
        return None

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        del variables
        seen_queries.append(query)
        if "create_item" in query:
            return {"data": {"create_item": {"id": "111"}}}
        raise AssertionError("Se esperaba create_item para lead nuevo")

    monkeypatch.setattr(adapter, "_find_item_by_phone", _fake_find_item_by_phone)
    monkeypatch.setattr(adapter, "_gql", _fake_gql)

    lead = Lead(phone="+52 1446-105-1272", attributes={})

    result = await adapter.upsert_lead(lead)

    assert result == "111"
    assert lead.attributes.get("monday_id") == "111"
    assert any("create_item" in query for query in seen_queries)


@pytest.mark.asyncio
async def test_existing_lead_by_phone_updates(
    adapter: MondayCRMAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_queries: list[str] = []

    async def _fake_find_item_by_phone(phone: str) -> str | None:
        assert phone == "4461051272"
        return "11874306730"

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        del variables
        seen_queries.append(query)
        if "change_multiple_column_values" in query:
            return {"data": {"change_multiple_column_values": {"id": "11874306730"}}}
        raise AssertionError("No se esperaba create_item cuando existe lead por telefono")

    monkeypatch.setattr(adapter, "_find_item_by_phone", _fake_find_item_by_phone)
    monkeypatch.setattr(adapter, "_gql", _fake_gql)

    lead = Lead(phone="4461051272", attributes={})

    result = await adapter.upsert_lead(lead)

    assert result == "11874306730"
    assert lead.attributes.get("monday_id") == "11874306730"
    assert any("change_multiple_column_values" in query for query in seen_queries)
    assert all("create_item" not in query for query in seen_queries)


@pytest.mark.asyncio
async def test_known_monday_id_skips_phone_search(
    adapter: MondayCRMAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_queries: list[str] = []

    async def _fake_find_item_by_phone(_: str) -> str | None:
        raise AssertionError("No debe buscar por telefono cuando ya hay monday_id")

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        del variables
        seen_queries.append(query)
        if "change_multiple_column_values" in query:
            return {"data": {"change_multiple_column_values": {"id": "11874306730"}}}
        raise AssertionError("Se esperaba update cuando monday_id es conocido")

    monkeypatch.setattr(adapter, "_find_item_by_phone", _fake_find_item_by_phone)
    monkeypatch.setattr(adapter, "_gql", _fake_gql)

    lead = Lead(phone="4461051272", attributes={"monday_id": "11874306730"})

    result = await adapter.upsert_lead(lead)

    assert result == "11874306730"
    assert any("change_multiple_column_values" in query for query in seen_queries)


def test_normalize_phone(adapter: MondayCRMAdapter) -> None:
    assert adapter._normalize_phone("+52 446 105 1272") == "524461051272"
    assert adapter._normalize_phone("446-105-1272") == "4461051272"
    assert adapter._normalize_phone("  +1 (555) 000-0000  ") == "15550000000"


@pytest.mark.asyncio
async def test_empty_phone_creates_without_search(
    adapter: MondayCRMAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_queries: list[str] = []

    async def _fake_find_item_by_phone(_: str) -> str | None:
        raise AssertionError("No debe buscar por telefono cuando esta vacio")

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        del variables
        seen_queries.append(query)
        if "create_item" in query:
            return {"data": {"create_item": {"id": "222"}}}
        raise AssertionError("Se esperaba create_item cuando telefono esta vacio")

    monkeypatch.setattr(adapter, "_find_item_by_phone", _fake_find_item_by_phone)
    monkeypatch.setattr(adapter, "_gql", _fake_gql)

    lead = Lead(phone="", attributes={})

    result = await adapter.upsert_lead(lead)

    assert result == "222"
    assert lead.attributes.get("monday_id") == "222"
    assert any("create_item" in query for query in seen_queries)
