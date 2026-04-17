from pathlib import Path
from typing import get_args

import pytest

from core.brand.loader import BrandValidationError, load_brand
from core.brand.schema import WhatsAppChannelConfig


def test_example_brand_loads_successfully() -> None:
    brand = load_brand(Path("brand"))
    valid_provider_types = get_args(WhatsAppChannelConfig.model_fields["provider_type"].annotation)

    assert brand.brand.display_name == "SelecTrucks Zapata"
    assert brand.channels.whatsapp.provider_type in valid_provider_types
    assert brand.fsm.initial_state == "idle"
    assert "idle" in brand.fsm.states
    assert "Estefania" in brand.prompt


def test_invalid_brand_raises_clear_validation_error() -> None:
    invalid_brand_path = Path("tests/fixtures/invalid_brand_missing_display_name")

    with pytest.raises(BrandValidationError) as exc_info:
        load_brand(invalid_brand_path)

    assert "brand.yaml" in str(exc_info.value)
    assert "display_name" in str(exc_info.value)
