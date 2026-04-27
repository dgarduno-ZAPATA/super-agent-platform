from __future__ import annotations

import json

import pytest

from adapters.crm import monday_adapter
from adapters.crm.monday_adapter import COL_NOMBRE_COMPLETO, COL_VEHICULO, MondayCRMAdapter
from core.domain.lead import Lead


def _build_adapter(monkeypatch) -> MondayCRMAdapter:
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
        "lead_name": "nombre_contacto",
        "phone": "telefono_principal",
        "source": "fuente_lead",
        "vehicle_interest": "vehiculo_interes",
        "city": "ciudad",
        "fsm_state": "etapa_bot",
    }
    monkeypatch.setattr(MondayCRMAdapter, "_load_stage_map", staticmethod(lambda: stage_map))
    monkeypatch.setattr(MondayCRMAdapter, "_load_field_map", staticmethod(lambda: field_map))
    return MondayCRMAdapter(api_key="test-key", board_id="123")


def test_resolve_stage_label_uses_stage_map_key(monkeypatch) -> None:
    adapter = _build_adapter(monkeypatch)

    assert adapter._resolve_stage_label("qualified") == "Calificando"


def test_resolve_stage_label_maps_from_fsm_state(monkeypatch) -> None:
    adapter = _build_adapter(monkeypatch)

    assert adapter._resolve_stage_label("greeting") == "Conversando"


def test_resolve_stage_label_fallback_logs_warning(monkeypatch) -> None:
    adapter = _build_adapter(monkeypatch)
    captured: list[tuple[str, dict[str, object]]] = []

    def _fake_warning(event: str, **kwargs: object) -> None:
        captured.append((event, kwargs))

    monkeypatch.setattr(monday_adapter.logger, "warning", _fake_warning)

    assert adapter._resolve_stage_label("stage_inexistente") == "Nuevo"
    assert captured == [
        (
            "monday_stage_label_not_found",
            {"stage": "stage_inexistente", "fallback": "Nuevo"},
        )
    ]


@pytest.mark.asyncio
async def test_upsert_lead_without_name_sends_provisional_name(monkeypatch) -> None:
    adapter = _build_adapter(monkeypatch)
    captured_cols: dict[str, object] = {}

    async def _fake_find_item_by_phone(phone: str) -> str | None:
        assert phone == "521442556824"
        return "123"

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        del query
        assert variables is not None
        raw_cols = variables["cols"]
        assert isinstance(raw_cols, str)
        captured_cols.update(json.loads(raw_cols))
        return {"data": {"change_multiple_column_values": {"id": "123"}}}

    monkeypatch.setattr(adapter, "_find_item_by_phone", _fake_find_item_by_phone)
    monkeypatch.setattr(adapter, "_gql", _fake_gql)

    await adapter.upsert_lead(
        Lead(
            phone="521442556824",
            name="",
            source="whatsapp_inbound",
            attributes={"last_message_text": "Hola buenas"},
        )
    )

    assert captured_cols[COL_NOMBRE_COMPLETO] == "Lead 6824"
    assert captured_cols["nombre_contacto"] == "Lead 6824"


@pytest.mark.asyncio
async def test_upsert_lead_includes_vehicle_interest_in_payload(monkeypatch) -> None:
    adapter = _build_adapter(monkeypatch)
    captured_cols: dict[str, object] = {}

    async def _fake_find_item_by_phone(phone: str) -> str | None:
        assert phone == "521442001111"
        return "123"

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        del query
        assert variables is not None
        raw_cols = variables["cols"]
        assert isinstance(raw_cols, str)
        captured_cols.update(json.loads(raw_cols))
        return {"data": {"change_multiple_column_values": {"id": "123"}}}

    monkeypatch.setattr(adapter, "_find_item_by_phone", _fake_find_item_by_phone)
    monkeypatch.setattr(adapter, "_gql", _fake_gql)

    await adapter.upsert_lead(
        Lead(
            phone="521442001111",
            name="Cliente Demo",
            source="whatsapp_inbound",
            attributes={
                "last_message_text": "Busco tracto",
                "vehicle_interest": "tracto",
                "fsm_state": "catalog_navigation",
            },
        )
    )

    assert captured_cols[COL_VEHICULO] == "tracto"
    assert captured_cols["vehiculo_interes"] == "tracto"
