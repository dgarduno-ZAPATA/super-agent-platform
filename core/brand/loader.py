from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import ValidationError

from core.brand.schema import (
    Brand,
    BrandConfig,
    CRMMappingConfig,
    ChannelsConfig,
    FunnelConfig,
    OutboundTemplatesConfig,
    PoliciesConfig,
    ProductsConfig,
    StrictConfigModel,
)


class BrandValidationError(ValueError):
    pass


SchemaT = TypeVar("SchemaT", bound=StrictConfigModel)


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BrandValidationError(f"{path.name}: file is required")

    try:
        raw_content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BrandValidationError(f"{path.name}: invalid YAML: {exc}") from exc

    if not isinstance(raw_content, dict):
        raise BrandValidationError(f"{path.name}: root value must be a mapping")

    return raw_content


def _format_validation_error(file_name: str, error: ValidationError) -> str:
    formatted_errors: list[str] = []

    for issue in error.errors():
        location = ".".join(str(part) for part in issue["loc"])
        formatted_errors.append(f"{file_name}: field '{location}': {issue['msg']}")

    return "; ".join(formatted_errors)


def _load_schema(path: Path, schema: type[SchemaT]) -> SchemaT:
    payload = _load_yaml_file(path)

    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise BrandValidationError(_format_validation_error(path.name, exc)) from exc


def load_brand(path: Path) -> Brand:
    brand_path = path.resolve()

    prompt_path = brand_path / "prompt.md"
    if not prompt_path.exists():
        raise BrandValidationError(f"{prompt_path.name}: file is required")

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise BrandValidationError(f"{prompt_path.name}: prompt cannot be empty")

    return Brand(
        brand=_load_schema(brand_path / "brand.yaml", BrandConfig),
        funnel=_load_schema(brand_path / "funnel.yaml", FunnelConfig),
        outbound_templates=_load_schema(
            brand_path / "outbound_templates.yaml", OutboundTemplatesConfig
        ),
        products=_load_schema(brand_path / "products.yaml", ProductsConfig),
        policies=_load_schema(brand_path / "policies.yaml", PoliciesConfig),
        crm_mapping=_load_schema(brand_path / "crm_mapping.yaml", CRMMappingConfig),
        channels=_load_schema(brand_path / "channels.yaml", ChannelsConfig),
        prompt=prompt,
    )
