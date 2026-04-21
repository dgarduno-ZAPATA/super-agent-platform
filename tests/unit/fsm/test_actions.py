from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.brand.schema import Brand
from core.domain.branch import Branch
from core.domain.messaging import MessageDeliveryReceipt
from core.fsm.actions import FSMActionDependencies, build_default_action_registry


class FakeSessionRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, dict[str, object]]] = []

    async def update_state(
        self, session_id: UUID, new_state: str, context: dict[str, object]
    ) -> None:
        self.calls.append((session_id, new_state, context))


class FakeCRMOutboxRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def enqueue_operation(
        self, aggregate_id: str, operation: str, payload: dict[str, object]
    ) -> UUID:
        self.calls.append(
            {
                "aggregate_id": aggregate_id,
                "operation": operation,
                "payload": payload,
            }
        )
        return UUID("00000000-0000-0000-0000-000000000001")


class FakeMessagingProvider:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []
        self.sent_documents: list[dict[str, str]] = []

    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        self.sent_messages.append({"to": to, "text": text, "correlation_id": correlation_id})
        return MessageDeliveryReceipt(
            message_id="out-001",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        self.sent_documents.append(
            {
                "to": to,
                "document_url": document_url,
                "filename": filename,
                "correlation_id": correlation_id,
            }
        )
        return MessageDeliveryReceipt(
            message_id="out-002",
            provider="fake",
            status="accepted",
            correlation_id=correlation_id,
            metadata={},
        )

    async def send_image(self, to: str, image_url: str, caption: str | None, correlation_id: str):
        del to, image_url, caption, correlation_id
        raise NotImplementedError

    async def send_audio(self, to: str, audio_url: str, correlation_id: str):
        del to, audio_url, correlation_id
        raise NotImplementedError

    async def mark_read(self, message_id: str) -> None:
        del message_id
        raise NotImplementedError

    @staticmethod
    def parse_inbound_event(raw_payload: dict[str, object]):
        del raw_payload
        raise NotImplementedError


class FakeBranchProvider:
    def __init__(self) -> None:
        self._branches = [
            Branch(
                sucursal_key="queretaro",
                display_name="Sucursal Queretaro",
                centro_sheet="Queretaro",
                phones=["5211111111111", "5212222222222"],
                activa=True,
            )
        ]

    def list_branches(self) -> list[Branch]:
        return self._branches

    def get_branch_by_centro(self, centro: str) -> Branch | None:
        normalized = centro.strip().casefold()
        for branch in self._branches:
            if branch.centro_sheet.strip().casefold() == normalized:
                return branch
        return None

    def get_branch_by_key(self, key: str) -> Branch | None:
        normalized = key.strip().casefold()
        for branch in self._branches:
            if branch.sucursal_key.strip().casefold() == normalized:
                return branch
        return None


def _build_brand() -> Brand:
    return Brand.model_validate(
        {
            "brand": {
                "name": "raul_rodriguez",
                "display_name": "Raul Rodriguez",
                "default_locale": "es_MX",
                "timezone": "America/Mexico_City",
                "primary_color": "#005BAC",
            },
            "funnel": {
                "states": [
                    {
                        "name": "idle",
                        "description": "Estado inicial",
                        "allowed_transitions": ["greeting"],
                    },
                    {
                        "name": "greeting",
                        "description": "Saludo",
                        "allowed_transitions": ["idle"],
                    },
                ]
            },
            "outbound_templates": {"campaigns": []},
            "products": {
                "products": [
                    {
                        "sku": "FL-CASCADIA-2020",
                        "name": "Freightliner Cascadia 2020",
                        "description": "Unidad demo",
                        "metadata": {"document_url": "https://cdn.example.com/fichas/cascadia.pdf"},
                    }
                ]
            },
            "policies": {
                "working_hours": {
                    "monday": {"start": "09:00", "end": "18:00"},
                    "tuesday": {"start": "09:00", "end": "18:00"},
                    "wednesday": {"start": "09:00", "end": "18:00"},
                    "thursday": {"start": "09:00", "end": "18:00"},
                    "friday": {"start": "09:00", "end": "18:00"},
                    "saturday": {"start": "09:00", "end": "14:00"},
                    "sunday": {"start": "09:00", "end": "14:00"},
                },
                "max_messages_per_day_per_lead": 10,
                "opt_out_keywords": ["stop"],
                "handoff_keywords": ["asesor"],
                "handoff_response_text": "Un asesor te contactara pronto.",
                "forbidden_terms": [],
            },
            "crm_mapping": {
                "provider_type": "monday",
                "stage_map": {"qualified": "Perfilado"},
                "field_map": {"lead_name": "nombre_contacto"},
            },
            "channels": {
                "whatsapp": {
                    "provider_type": "evolution",
                    "api_version": "v2",
                    "phone_number_id": "123",
                    "template_namespace": "test",
                }
            },
            "fsm": {
                "initial_state": "idle",
                "states": {
                    "idle": {"description": "idle", "allowed_transitions": [], "on_enter": [], "on_exit": []}
                },
            },
            "prompt": "Prompt de prueba",
        }
    )


@pytest.mark.asyncio
async def test_update_session_action_uses_real_repository() -> None:
    repo = FakeSessionRepository()
    registry = build_default_action_registry(
        FSMActionDependencies(session_repository=repo),
    )
    session_id = uuid4()

    await registry["update_session"](
        {
            "session_id": str(session_id),
            "new_state": "qualification",
            "session_context": {"foo": "bar"},
        }
    )

    assert len(repo.calls) == 1
    assert repo.calls[0][0] == session_id
    assert repo.calls[0][1] == "qualification"
    assert repo.calls[0][2] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_update_crm_stage_action_enqueues_outbox_operation() -> None:
    outbox = FakeCRMOutboxRepository()
    registry = build_default_action_registry(
        FSMActionDependencies(crm_outbox_repository=outbox, brand=_build_brand()),
    )

    await registry["update_crm_stage"](
        {
            "lead_id": "00000000-0000-0000-0000-000000000123",
            "new_state": "qualification",
            "old_state": "discovery",
        }
    )

    assert len(outbox.calls) == 1
    assert outbox.calls[0]["operation"] == "change_stage"
    payload = outbox.calls[0]["payload"]
    assert payload["new_stage"] == "Perfilado"
    assert payload["lead_id"] == "00000000-0000-0000-0000-000000000123"
    assert "fsm:discovery->qualification" in str(payload["reason"])


@pytest.mark.asyncio
async def test_notify_agent_action_sends_whatsapp_to_branch_phones() -> None:
    messaging = FakeMessagingProvider()
    registry = build_default_action_registry(
        FSMActionDependencies(
            messaging_provider=messaging,
            branch_provider=FakeBranchProvider(),
        ),
    )

    await registry["notify_agent"](
        {
            "sucursal_key": "queretaro",
            "phone": "5214421234567",
            "name": "Cliente Demo",
            "new_state": "handoff_pending",
            "correlation_id": "wamid-001",
        }
    )

    assert len(messaging.sent_messages) == 2
    recipients = {item["to"] for item in messaging.sent_messages}
    assert recipients == {"5211111111111", "5212222222222"}
    assert all(item["correlation_id"] == "wamid-001" for item in messaging.sent_messages)


@pytest.mark.asyncio
async def test_send_document_action_uses_brand_products_catalog() -> None:
    messaging = FakeMessagingProvider()
    registry = build_default_action_registry(
        FSMActionDependencies(
            messaging_provider=messaging,
            brand=_build_brand(),
        ),
    )

    await registry["send_document"](
        {
            "phone": "5214421234567",
            "product_sku": "FL-CASCADIA-2020",
            "correlation_id": "wamid-002",
            "session_context": {"last_inbound_message": {"text": "Quiero ficha del Cascadia"}},
        }
    )

    assert len(messaging.sent_documents) == 1
    sent = messaging.sent_documents[0]
    assert sent["to"] == "5214421234567"
    assert sent["document_url"] == "https://cdn.example.com/fichas/cascadia.pdf"
    assert sent["filename"] == "FL-CASCADIA-2020.pdf"
    assert sent["correlation_id"] == "wamid-002"
