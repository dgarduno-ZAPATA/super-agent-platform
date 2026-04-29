from __future__ import annotations

from typing import Any

import pytest

from adapters.crm import monday_adapter
from adapters.crm.monday_adapter import MondayCRMAdapter


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
        "won": "Handoff Hecho",
        "lost": "Nuevo",
        "do_not_contact": "Nuevo",
    }
    field_map: dict[str, str] = {}
    monkeypatch.setattr(MondayCRMAdapter, "_load_stage_map", staticmethod(lambda: stage_map))
    monkeypatch.setattr(MondayCRMAdapter, "_load_field_map", staticmethod(lambda: field_map))
    return MondayCRMAdapter(api_key="test-key", board_id="123")


@pytest.mark.asyncio
async def test_add_note_success(adapter: MondayCRMAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
    captured_logs: list[tuple[str, dict[str, Any]]] = []

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        assert "create_update" in query
        assert variables is not None
        assert variables["item"] == "11874306730"
        assert "[sistema]: resumen breve" in str(variables["body"])
        return {"data": {"create_update": {"id": "123"}}}

    def _fake_info(event: str, **kwargs: object) -> None:
        captured_logs.append((event, kwargs))

    monkeypatch.setattr(adapter, "_gql", _fake_gql)
    monkeypatch.setattr(monday_adapter.logger, "info", _fake_info)

    await adapter.add_note("11874306730", "resumen breve", "sistema")

    assert captured_logs
    assert captured_logs[0][0] == "monday_note_added"
    assert captured_logs[0][1]["update_id"] == "123"


@pytest.mark.asyncio
async def test_add_note_failure_does_not_raise(
    adapter: MondayCRMAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_logs: list[tuple[str, dict[str, Any]]] = []

    async def _fake_gql(
        query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        del query
        del variables
        raise RuntimeError("boom")

    def _fake_warning(event: str, **kwargs: object) -> None:
        captured_logs.append((event, kwargs))

    monkeypatch.setattr(adapter, "_gql", _fake_gql)
    monkeypatch.setattr(monday_adapter.logger, "warning", _fake_warning)

    await adapter.add_note("11874306730", "resumen breve", "sistema")

    assert captured_logs
    assert captured_logs[0][0] == "monday_note_failed"
