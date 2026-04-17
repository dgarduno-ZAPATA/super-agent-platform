from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

import structlog

from core.domain.lead import Lead
from core.ports.crm_provider import CRMProvider

logger = structlog.get_logger("super_agent_platform.adapters.crm.monday_adapter")


class MondayCRMAdapter(CRMProvider):
    async def upsert_lead(self, lead: Lead) -> str:
        await asyncio.sleep(0.1)
        logger.info("monday_api_mock_call", operation="upsert_lead", phone=lead.phone)
        return f"monday-{uuid4()}"

    async def change_stage(self, lead_id: str, new_stage: str, reason: str | None = None) -> None:
        await asyncio.sleep(0.1)
        logger.info(
            "monday_api_mock_call",
            operation="change_stage",
            lead_id=lead_id,
            new_stage=new_stage,
            reason=reason,
        )

    async def add_note(self, lead_id: str, note: str, author: str) -> None:
        await asyncio.sleep(0.1)
        logger.info(
            "monday_api_mock_call",
            operation="add_note",
            lead_id=lead_id,
            author=author,
            note=note,
        )

    async def assign_owner(self, lead_id: str, owner_id: str) -> None:
        await asyncio.sleep(0.1)
        logger.info(
            "monday_api_mock_call",
            operation="assign_owner",
            lead_id=lead_id,
            owner_id=owner_id,
        )

    async def mark_do_not_contact(self, lead_id: str, reason: str) -> None:
        await asyncio.sleep(0.1)
        logger.info(
            "monday_api_mock_call",
            operation="mark_do_not_contact",
            lead_id=lead_id,
            reason=reason,
        )

    async def schedule_reactivation(self, lead_id: str, not_before: datetime) -> None:
        await asyncio.sleep(0.1)
        logger.info(
            "monday_api_mock_call",
            operation="schedule_reactivation",
            lead_id=lead_id,
            not_before=not_before.isoformat(),
        )
