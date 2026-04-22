from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from core.ports.branch_provider import BranchProvider
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import CRMOutboxRepository, SessionRepository

if TYPE_CHECKING:
    from core.brand.schema import Brand, ProductConfig

ActionFunction = Callable[[dict[str, object]], Awaitable[None]]
ActionRegistry = dict[str, ActionFunction]

logger = structlog.get_logger("super_agent_platform.core.fsm.actions")


@dataclass(frozen=True, slots=True)
class FSMActionDependencies:
    session_repository: SessionRepository | None = None
    crm_outbox_repository: CRMOutboxRepository | None = None
    messaging_provider: MessagingProvider | None = None
    branch_provider: BranchProvider | None = None
    brand: Brand | None = None


async def log_transition_action(context: dict[str, object]) -> None:
    logger.info(
        "fsm_transition_action",
        fsm_event=context.get("event"),
        old_state=context.get("old_state"),
        new_state=context.get("new_state"),
        guard=context.get("guard"),
    )


def _coerce_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return UUID(value.strip())
        except ValueError:
            return None
    return None


def _coerce_str(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _extract_nested_string(context: dict[str, object], keys: list[str]) -> str | None:
    for key in keys:
        direct = _coerce_str(context.get(key))
        if direct is not None:
            return direct

    for container_key in ("session_context", "lead_attributes", "last_inbound_message"):
        container = _as_mapping(context.get(container_key))
        for key in keys:
            nested = _coerce_str(container.get(key))
            if nested is not None:
                return nested

    return None


def _resolve_crm_stage(
    context: dict[str, object], dependencies: FSMActionDependencies
) -> str | None:
    explicit_stage = _coerce_str(context.get("stage")) or _coerce_str(context.get("crm_stage"))
    if explicit_stage is not None:
        return explicit_stage

    state = _coerce_str(context.get("new_state")) or _coerce_str(context.get("current_state"))
    if state is None:
        return None

    if dependencies.brand is None:
        return state

    stage_key_by_state = {
        "idle": "new_lead",
        "greeting": "contacted",
        "discovery": "contacted",
        "qualification": "qualified",
        "catalog_navigation": "quoted",
        "document_delivery": "quoted",
        "objection_handling": "nurture",
        "appointment_flow": "quoted",
        "handoff_pending": "handoff",
        "handoff_active": "handoff",
        "cooldown": "nurture",
        "closed": "lost",
    }
    stage_key = stage_key_by_state.get(state)
    if stage_key is None:
        return state
    return dependencies.brand.crm_mapping.stage_map.get(stage_key, stage_key)


def _resolve_branch_phones(
    context: dict[str, object],
    dependencies: FSMActionDependencies,
) -> tuple[str | None, list[str]]:
    branch_provider = dependencies.branch_provider
    if branch_provider is None:
        return None, []

    branch_key = _extract_nested_string(context, ["branch_key", "sucursal_key"])
    if branch_key is not None:
        branch = branch_provider.get_branch_by_key(branch_key)
        if branch is not None:
            return branch.sucursal_key, list(dict.fromkeys(branch.phones))

    centro = _extract_nested_string(context, ["centro_sheet", "centro", "centro_inventario"])
    if centro is not None:
        branch = branch_provider.get_branch_by_centro(centro)
        if branch is not None:
            return branch.sucursal_key, list(dict.fromkeys(branch.phones))

    branches = branch_provider.list_branches()
    if not branches:
        return None, []
    return branches[0].sucursal_key, list(dict.fromkeys(branches[0].phones))


def _resolve_product(
    context: dict[str, object],
    dependencies: FSMActionDependencies,
) -> ProductConfig | None:
    if dependencies.brand is None:
        return None

    sku_hint = _extract_nested_string(context, ["product_sku", "sku"])
    if sku_hint is not None:
        for product in dependencies.brand.products.products:
            if product.sku.casefold() == sku_hint.casefold():
                return product

    name_hint = _extract_nested_string(
        context, ["product_name", "vehiculo_interes", "vehicle_interest"]
    )
    if name_hint is not None:
        lowered = name_hint.casefold()
        for product in dependencies.brand.products.products:
            if lowered in product.name.casefold():
                return product

    if dependencies.brand.products.products:
        return dependencies.brand.products.products[0]
    return None


def _resolve_document_target(
    context: dict[str, object],
    dependencies: FSMActionDependencies,
) -> tuple[str, str]:
    explicit_url = _extract_nested_string(context, ["document_url", "ficha_url", "brochure_url"])
    if explicit_url is not None:
        filename = _coerce_str(context.get("document_filename")) or Path(explicit_url).name
        return explicit_url, (filename or "ficha.pdf")

    product = _resolve_product(context, dependencies)
    if product is not None:
        for key in ("document_url", "ficha_url", "brochure_url", "pdf_url", "url"):
            candidate = _coerce_str(product.metadata.get(key))
            if candidate is not None:
                return candidate, f"{product.sku}.pdf"
        return f"https://docs.example.com/{product.sku}.pdf", f"{product.sku}.pdf"

    return "https://docs.example.com/catalogo.pdf", "catalogo.pdf"


def build_default_action_registry(
    dependencies: FSMActionDependencies | None = None,
) -> ActionRegistry:
    deps = dependencies or FSMActionDependencies()

    async def update_session_action(context: dict[str, object]) -> None:
        if deps.session_repository is None:
            logger.info("fsm_update_session_skipped", reason="missing_session_repository")
            return

        session_id = _coerce_uuid(context.get("session_id"))
        state = _coerce_str(context.get("new_state")) or _coerce_str(context.get("current_state"))
        if session_id is None or state is None:
            logger.warning(
                "fsm_update_session_skipped",
                reason="missing_session_id_or_state",
                session_id=context.get("session_id"),
                state=state,
            )
            return

        session_context = _as_mapping(context.get("session_context"))
        await deps.session_repository.update_state(
            session_id=session_id,
            new_state=state,
            context=session_context,
        )
        logger.info("fsm_update_session_done", session_id=str(session_id), new_state=state)

    async def update_crm_stage_action(context: dict[str, object]) -> None:
        if deps.crm_outbox_repository is None:
            logger.info("fsm_update_crm_stage_skipped", reason="missing_crm_outbox_repository")
            return

        stage = _resolve_crm_stage(context, deps)
        lead_id = _coerce_str(context.get("lead_external_crm_id")) or _coerce_str(
            context.get("lead_id")
        )
        if stage is None or lead_id is None:
            logger.warning(
                "fsm_update_crm_stage_skipped",
                reason="missing_stage_or_lead_id",
                lead_id=lead_id,
                stage=stage,
            )
            return

        aggregate_id = _coerce_str(context.get("lead_id")) or lead_id
        old_state = _coerce_str(context.get("old_state")) or "unknown"
        new_state = _coerce_str(context.get("new_state")) or "unknown"
        await deps.crm_outbox_repository.enqueue_operation(
            aggregate_id=aggregate_id,
            operation="change_stage",
            payload={
                "lead_id": lead_id,
                "new_stage": stage,
                "reason": f"fsm:{old_state}->{new_state}",
            },
        )
        logger.info("fsm_update_crm_stage_done", lead_id=lead_id, stage=stage)

    async def notify_agent_action(context: dict[str, object]) -> None:
        if deps.messaging_provider is None:
            logger.info("fsm_notify_agent_skipped", reason="missing_messaging_provider")
            return

        branch_key, phones = _resolve_branch_phones(context, deps)
        if not phones:
            logger.warning("fsm_notify_agent_skipped", reason="no_branch_phones_found")
            return

        customer_phone = _coerce_str(context.get("phone")) or "desconocido"
        customer_name = _coerce_str(context.get("name")) or "Cliente sin nombre"
        correlation_id = _coerce_str(context.get("correlation_id")) or "fsm-notify-agent"
        message = _coerce_str(context.get("handoff_message")) or (
            "[FSM Handoff]\n"
            f"Sucursal: {branch_key or 'sin_sucursal'}\n"
            f"Cliente: {customer_name}\n"
            f"Telefono: {customer_phone}\n"
            f"Estado: {_coerce_str(context.get('new_state')) or 'sin_estado'}"
        )
        for phone in phones:
            await deps.messaging_provider.send_text(
                to=phone,
                text=message,
                correlation_id=correlation_id,
            )
        logger.info("fsm_notify_agent_done", recipients=len(phones), branch_key=branch_key)

    async def send_document_action(context: dict[str, object]) -> None:
        if deps.messaging_provider is None:
            logger.info("fsm_send_document_skipped", reason="missing_messaging_provider")
            return

        to_phone = _coerce_str(context.get("phone"))
        if to_phone is None:
            logger.warning("fsm_send_document_skipped", reason="missing_phone")
            return

        correlation_id = _coerce_str(context.get("correlation_id")) or "fsm-send-document"
        document_url, filename = _resolve_document_target(context, deps)
        try:
            await deps.messaging_provider.send_document(
                to=to_phone,
                document_url=document_url,
                filename=filename,
                correlation_id=correlation_id,
            )
            logger.info(
                "fsm_send_document_done",
                to=to_phone,
                filename=filename,
                document_url=document_url,
            )
        except Exception as exc:
            logger.error(
                "fsm_send_document_failed",
                to=to_phone,
                filename=filename,
                document_url=document_url,
                correlation_id=correlation_id,
                error=str(exc),
            )
            await deps.messaging_provider.send_text(
                to=to_phone,
                text=(
                    "Te comparto que tenemos fichas tecnicas disponibles. "
                    "Quieres que un asesor te las envie directamente?"
                ),
                correlation_id=correlation_id,
            )
            logger.info(
                "fsm_send_document_fallback_text_sent",
                to=to_phone,
                correlation_id=correlation_id,
            )

    return {
        "log_transition": log_transition_action,
        "update_session": update_session_action,
        "update_crm_stage": update_crm_stage_action,
        "notify_agent": notify_agent_action,
        "send_document": send_document_action,
    }
