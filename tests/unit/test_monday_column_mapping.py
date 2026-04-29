from __future__ import annotations

import pathlib
from collections.abc import Iterator

import yaml


def _find_empty_values(value: object, path: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield from _find_empty_values(nested, next_path)
        return
    if isinstance(value, str) and not value.strip():
        yield path


def test_no_empty_column_ids_in_mapping() -> None:
    mapping = yaml.safe_load(pathlib.Path("brand/crm_mapping.yaml").read_text(encoding="utf-8"))
    empties = list(_find_empty_values(mapping))
    assert empties == [], f"Campos vacíos en crm_mapping.yaml: {empties}"


def test_crm_mapping_has_required_fields() -> None:
    mapping = yaml.safe_load(pathlib.Path("brand/crm_mapping.yaml").read_text(encoding="utf-8"))
    required = ["lead_name", "phone", "vehicle_interest", "city"]
    mapping_text = str(mapping)
    for field in required:
        assert field in mapping_text, f"Campo requerido '{field}' no encontrado en crm_mapping.yaml"
