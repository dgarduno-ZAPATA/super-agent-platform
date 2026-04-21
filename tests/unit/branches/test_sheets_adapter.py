from __future__ import annotations

from datetime import UTC, datetime, timedelta

from adapters.branches.sheets_adapter import SheetsBranchAdapter


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def tick(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


def _csv_fixture() -> str:
    return (
        "sucursal_key,display_name,centro_sheet,telefono_encargado,nombre_encargado,activa\n"
        "queretaro,Sucursal Queretaro,Queretaro,5211111111111,Ana,TRUE\n"
        "queretaro,Sucursal Queretaro,Queretaro,5212222222222,Ana,TRUE\n"
        "leon,Sucursal Leon,Leon,5213333333333,Luis,FALSE\n"
        "fallback,Sucursal Fallback,CDMX,5214444444444,Operaciones,TRUE\n"
    )


def test_parse_csv_groups_multiple_rows_per_branch() -> None:
    adapter = SheetsBranchAdapter(
        csv_url="https://example.com/branches.csv",
        http_get=lambda _: _csv_fixture(),
        cache_ttl_seconds=600,
    )

    branches = adapter.list_branches()

    assert len(branches) == 2
    assert branches[0].sucursal_key == "queretaro"
    assert branches[0].phones == ["5211111111111", "5212222222222"]


def test_filters_inactive_branches() -> None:
    adapter = SheetsBranchAdapter(
        csv_url="https://example.com/branches.csv",
        http_get=lambda _: _csv_fixture(),
        cache_ttl_seconds=600,
    )

    keys = [item.sucursal_key for item in adapter.list_branches()]

    assert "leon" not in keys
    assert "queretaro" in keys


def test_get_branch_by_centro_existing_and_missing() -> None:
    adapter = SheetsBranchAdapter(
        csv_url="https://example.com/branches.csv",
        http_get=lambda _: _csv_fixture(),
        cache_ttl_seconds=600,
    )

    found = adapter.get_branch_by_centro("queretaro")
    missing = adapter.get_branch_by_centro("merida")

    assert found is not None
    assert found.sucursal_key == "queretaro"
    assert missing is None


def test_cache_avoids_second_http_request() -> None:
    calls = {"count": 0}
    clock = _Clock(datetime(2026, 4, 20, 12, 0, tzinfo=UTC))

    def fake_http_get(_: str) -> str:
        calls["count"] += 1
        return _csv_fixture()

    adapter = SheetsBranchAdapter(
        csv_url="https://example.com/branches.csv",
        http_get=fake_http_get,
        cache_ttl_seconds=600,
        now_provider=clock,
    )

    adapter.list_branches()
    clock.tick(seconds=60)
    adapter.list_branches()

    assert calls["count"] == 1
