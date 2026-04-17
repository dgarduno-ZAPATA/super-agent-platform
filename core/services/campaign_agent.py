from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import structlog

from core.brand.schema import Brand, OutboundCampaignConfig
from core.domain.lead import LeadProfile
from core.ports.repositories import LeadProfileRepository, OutboundQueueRepository

logger = structlog.get_logger("super_agent_platform.core.services.campaign_agent")


class CampaignAgent:
    def __init__(
        self,
        lead_profile_repository: LeadProfileRepository,
        outbound_queue_repository: OutboundQueueRepository,
        brand: Brand,
    ) -> None:
        self._lead_profile_repository = lead_profile_repository
        self._outbound_queue_repository = outbound_queue_repository
        self._brand = brand

    async def schedule_campaign(self, campaign_key: str) -> None:
        campaign = self._find_campaign(campaign_key)
        days_inactive = self._resolve_days_inactive(campaign)
        leads = await self._lead_profile_repository.get_dormant_leads(
            days_inactive=days_inactive,
            limit=100,
        )
        campaign_id = uuid4()
        now = datetime.now(UTC)

        for index, lead in enumerate(leads):
            scheduled_at = now + timedelta(minutes=index)
            payload: dict[str, object] = {
                "to": lead.phone,
                "text": self._render_template(campaign.template_text, lead),
                "campaign_key": campaign.key,
                "lead_name": lead.name,
            }
            await self._outbound_queue_repository.enqueue(
                lead_id=lead.id,
                campaign_id=campaign_id,
                payload=payload,
                priority=1,
                scheduled_at=scheduled_at,
            )

        logger.info(
            "campaign_scheduled",
            campaign_key=campaign_key,
            campaign_id=str(campaign_id),
            leads_enqueued=len(leads),
            priority=1,
        )

    def _find_campaign(self, campaign_key: str) -> OutboundCampaignConfig:
        for campaign in self._brand.outbound_templates.campaigns:
            if campaign.key == campaign_key:
                return campaign
        raise ValueError(f"unknown campaign key: {campaign_key}")

    @staticmethod
    def _resolve_days_inactive(campaign: OutboundCampaignConfig) -> int:
        raw = campaign.audience_filter.get("days_inactive")
        if isinstance(raw, int) and raw > 0:
            return raw
        return 90

    @staticmethod
    def _render_template(template_text: str, lead: LeadProfile) -> str:
        name = lead.name or "cliente"
        return template_text.format(name=name, phone=lead.phone)
