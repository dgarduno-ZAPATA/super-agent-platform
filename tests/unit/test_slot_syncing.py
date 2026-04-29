from adapters.crm.monday_adapter import (
    COLUMNS_EXCLUDE_FROM_SYNC,
    _diff_columns,
    _snapshot_lead_columns,
)


def test_first_sync_sends_all() -> None:
    cols = {"col_a": "valor1", "col_b": {"label": "X"}}
    result = _diff_columns({}, cols)
    assert result == cols


def test_no_changes_returns_empty() -> None:
    cols = {"col_a": "valor1"}
    snap = _snapshot_lead_columns(cols)
    result = _diff_columns(snap, cols)
    assert result == {}


def test_changed_column_returned() -> None:
    cols_before = {"col_a": "valor1", "col_b": "valor2"}
    snap = _snapshot_lead_columns(cols_before)
    cols_after = {"col_a": "valor1", "col_b": "nuevo_valor"}
    result = _diff_columns(snap, cols_after)
    assert "col_b" in result
    assert "col_a" not in result


def test_new_column_added() -> None:
    cols_before = {"col_a": "valor1"}
    snap = _snapshot_lead_columns(cols_before)
    cols_after = {"col_a": "valor1", "col_b": "nuevo"}
    result = _diff_columns(snap, cols_after)
    assert "col_b" in result


def test_dict_value_comparison_stable() -> None:
    cols_before = {"col_a": {"label": "X", "index": 1}}
    snap = _snapshot_lead_columns(cols_before)
    cols_after = {"col_a": {"index": 1, "label": "X"}}
    result = _diff_columns(snap, cols_after)
    assert result == {}


def test_snapshot_excludes_none_as_empty() -> None:
    cols = {"col_a": None}
    snap = _snapshot_lead_columns(cols)
    assert snap["col_a"] == ""


def test_excluded_columns_not_in_payload() -> None:
    assert "multiple_person_mm2kdy8q" in COLUMNS_EXCLUDE_FROM_SYNC
    assert "long_text_mm2k8vtc" in COLUMNS_EXCLUDE_FROM_SYNC
