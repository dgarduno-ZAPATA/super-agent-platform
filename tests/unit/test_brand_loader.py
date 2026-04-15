from pathlib import Path

import pytest

from core.brand.loader import BrandValidationError, load_brand


def test_example_brand_loads_successfully() -> None:
    brand = load_brand(Path("brand"))

    assert brand.brand.display_name == "SelecTrucks Zapata"
    assert brand.channels.whatsapp.provider_type == "meta_cloud_api"
    assert "Estefania" in brand.prompt


def test_invalid_brand_raises_clear_validation_error() -> None:
    invalid_brand_path = Path("tests/fixtures/invalid_brand_missing_display_name")

    with pytest.raises(BrandValidationError) as exc_info:
        load_brand(invalid_brand_path)

    assert "brand.yaml" in str(exc_info.value)
    assert "display_name" in str(exc_info.value)
