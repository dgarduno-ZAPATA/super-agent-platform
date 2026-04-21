from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.fsm.schema import FSMConfig


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InventoryColumnsConfig(StrictConfigModel):
    name: str = "nombre"
    description: str = "descripcion"
    price: str = "precio"
    availability: str = "disponible"
    category: str = "categoria"
    sku: str = "sku"


class BrandConfig(StrictConfigModel):
    name: str
    display_name: str
    default_locale: str
    timezone: str
    primary_color: str
    inventory_columns: InventoryColumnsConfig = Field(default_factory=InventoryColumnsConfig)


class FunnelStateConfig(StrictConfigModel):
    name: str
    description: str
    allowed_transitions: list[str]


class FunnelConfig(StrictConfigModel):
    states: list[FunnelStateConfig]

    @model_validator(mode="after")
    def validate_transitions(self) -> FunnelConfig:
        known_states = {state.name for state in self.states}

        for state in self.states:
            unknown_targets = set(state.allowed_transitions) - known_states
            if unknown_targets:
                unknown_target = sorted(unknown_targets)[0]
                raise ValueError(
                    f"state '{state.name}' references unknown transition '{unknown_target}'"
                )

        return self


class OutboundCampaignConfig(StrictConfigModel):
    key: str
    template_text: str
    window_start: str
    window_end: str
    cadence_hours: int
    audience_filter: dict[str, Any]


class OutboundTemplatesConfig(StrictConfigModel):
    campaigns: list[OutboundCampaignConfig]


class ProductConfig(StrictConfigModel):
    sku: str
    name: str
    description: str
    metadata: dict[str, Any]


class ProductsConfig(StrictConfigModel):
    products: list[ProductConfig]


class WorkingHoursRangeConfig(StrictConfigModel):
    start: str
    end: str


class PoliciesConfig(StrictConfigModel):
    working_hours: dict[str, WorkingHoursRangeConfig]
    max_messages_per_day_per_lead: int
    opt_out_keywords: list[str]
    handoff_keywords: list[str]
    handoff_response_text: str
    forbidden_terms: list[str]


class CRMMappingConfig(StrictConfigModel):
    stage_map: dict[str, str]
    field_map: dict[str, str]
    provider_type: str


class WhatsAppChannelConfig(StrictConfigModel):
    provider_type: Literal["evolution", "meta_cloud"]
    api_version: str
    phone_number_id: str
    template_namespace: str


class ChannelsConfig(StrictConfigModel):
    whatsapp: WhatsAppChannelConfig


class Brand(StrictConfigModel):
    brand: BrandConfig
    funnel: FunnelConfig
    outbound_templates: OutboundTemplatesConfig
    products: ProductsConfig
    policies: PoliciesConfig
    crm_mapping: CRMMappingConfig
    channels: ChannelsConfig
    fsm: FSMConfig
    prompt: str = Field(min_length=1)
