from pathlib import Path
from typing import get_args

import pytest

from core.brand.loader import BrandValidationError, load_brand, load_brand_config
from core.brand.schema import WhatsAppChannelConfig


def test_example_brand_loads_successfully() -> None:
    brand = load_brand(Path("brand"))
    valid_provider_types = get_args(WhatsAppChannelConfig.model_fields["provider_type"].annotation)

    assert brand.brand.display_name == "Raúl Rodríguez"
    assert brand.channels.whatsapp.provider_type in valid_provider_types
    assert brand.fsm.initial_state == "idle"
    assert "idle" in brand.fsm.states
    assert brand.prompt.strip()
    assert len(brand.prompt) >= 100


def test_invalid_brand_raises_clear_validation_error() -> None:
    invalid_brand_path = Path("tests/fixtures/invalid_brand_missing_display_name")

    with pytest.raises(BrandValidationError) as exc_info:
        load_brand(invalid_brand_path)

    assert "brand.yaml" in str(exc_info.value)
    assert "display_name" in str(exc_info.value)


def test_brand_loader_respects_brand_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    brand_dir = tmp_path / "testbrand"
    brand_dir.mkdir()
    (brand_dir / "brand.yaml").write_text(
        "\n".join(
            [
                "name: TestBrand",
                "slug: testbrand",
                "display_name: Test Bot",
                "default_locale: es-MX",
                "timezone: America/Mexico_City",
                "logo_url: ''",
                "primary_color: '#1a5276'",
                "accent_color: '#2e86c1'",
                "support_phone: ''",
                "admin_title: 'Panel Test'",
                "inventory_columns:",
                "  name: nombre",
                "  description: descripcion",
                "  price: precio",
                "  availability: disponible",
                "  category: categoria",
                "  sku: sku",
            ]
        ),
        encoding="utf-8",
    )
    (brand_dir / "funnel.yaml").write_text(
        "states:\n  - name: idle\n    description: idle\n    allowed_transitions: [idle]\n",
        encoding="utf-8",
    )
    (brand_dir / "outbound_templates.yaml").write_text("campaigns: []\n", encoding="utf-8")
    (brand_dir / "products.yaml").write_text("products: []\n", encoding="utf-8")
    (brand_dir / "policies.yaml").write_text(
        "\n".join(
            [
                "working_hours:",
                "  monday: {start: '09:00', end: '18:00'}",
                "max_messages_per_day_per_lead: 5",
                "opt_out_keywords: ['stop']",
                "handoff_keywords: ['asesor']",
                "handoff_response_text: 'ok'",
                "forbidden_terms: []",
            ]
        ),
        encoding="utf-8",
    )
    (brand_dir / "crm_mapping.yaml").write_text(
        "stage_map: {}\nfield_map: {}\nprovider_type: test\n",
        encoding="utf-8",
    )
    (brand_dir / "channels.yaml").write_text(
        "\n".join(
            [
                "whatsapp:",
                "  provider_type: evolution",
                "  api_version: v2",
                "  phone_number_id: '1'",
                "  template_namespace: test",
            ]
        ),
        encoding="utf-8",
    )
    (brand_dir / "fsm.yaml").write_text(
        "\n".join(
            [
                "initial_state: idle",
                "states:",
                "  idle:",
                "    description: estado inicial",
                "    allowed_transitions: []",
                "    on_enter: []",
                "    on_exit: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (brand_dir / "prompt.md").write_text("Prompt de prueba", encoding="utf-8")

    monkeypatch.setenv("BRAND_PATH", str(brand_dir))
    from core.config import get_settings

    get_settings.cache_clear()
    brand = load_brand_config()
    assert brand.brand.name == "TestBrand"
    get_settings.cache_clear()
