from __future__ import annotations

from core.brand.schema import BrandConfig, SystemMessagesConfig


def test_system_messages_defaults() -> None:
    cfg = SystemMessagesConfig()
    assert "asesor" in cfg.handoff_waiting
    assert "conectarte" in cfg.friction_escalation


def test_brand_config_has_system_messages() -> None:
    fields = BrandConfig.model_fields
    assert "system_messages" in fields
