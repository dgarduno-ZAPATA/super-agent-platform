from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.fsm.schema import FSMConfig


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InventoryColumnsConfig(StrictConfigModel):
    # Compat fields retained for backwards compatibility with older fixtures/configs.
    description: str = "descripcion"
    availability: str = "disponible"
    category: str = "categoria"
    sku: str = "VIN"
    sku_full: str = "VIN COMPLETO"
    name: str = "Modelo"
    brand: str = "Marca"
    year: str = "Año"
    price: str = "Precio Sug. de Venta"
    km: str = "Kilómetros"
    engine: str = "Motor"
    transmission: str = "Transmisión"
    color: str = "Color"
    location: str = "Centro"
    physical_location: str = "Ubicación Física"
    sleeper: str = "Dormitorio"
    paso: str = "Paso"
    promotion: str = "Promoción"
    image_url: str = "Imagen Portada"
    image_urls: str = "Imagenes Completas"


class SystemMessagesConfig(StrictConfigModel):
    handoff_waiting: str = "Ya le avisé a un asesor, en breve te atiende."
    friction_escalation: str = (
        "Entiendo que no he sido de ayuda. " "Déjame conectarte con un asesor ahora mismo."
    )


class BrandConfig(StrictConfigModel):
    name: str
    slug: str = "selectrucks-zapata"
    display_name: str
    default_locale: str
    timezone: str
    logo_url: str = ""
    primary_color: str
    accent_color: str = "#2e86c1"
    support_phone: str = ""
    admin_title: str = "Panel de Raúl"
    inventory_columns: InventoryColumnsConfig = Field(default_factory=InventoryColumnsConfig)
    system_messages: SystemMessagesConfig = Field(default_factory=SystemMessagesConfig)


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


class FallbackUsingFallbackConfig(StrictConfigModel):
    enabled: bool = False


class FallbackMessagesConfig(StrictConfigModel):
    both_llms_failed: list[str] = Field(default_factory=list)
    using_fallback: FallbackUsingFallbackConfig = Field(default_factory=FallbackUsingFallbackConfig)


class Brand(StrictConfigModel):
    brand: BrandConfig
    funnel: FunnelConfig
    outbound_templates: OutboundTemplatesConfig
    products: ProductsConfig
    policies: PoliciesConfig
    crm_mapping: CRMMappingConfig
    channels: ChannelsConfig
    fsm: FSMConfig
    fallback_messages: FallbackMessagesConfig = Field(default_factory=FallbackMessagesConfig)
    prompt: str = Field(min_length=1)
