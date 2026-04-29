import asyncio
import json
import re
from datetime import date, datetime
from typing import Any

import httpx
import structlog

from core.brand.loader import load_brand_config
from core.domain.lead import Lead
from core.ports.crm_provider import CRMProvider

logger = structlog.get_logger(__name__)

MONDAY_API_URL = "https://api.monday.com/v2"

COL_TELEFONO = "text_mm2k3epp"
COL_VEHICULO = "text_mm2ktbs7"
COL_ETAPA_BOT = "color_mm2kvwdj"
COL_SUCURSAL = "color_mm2k5p02"
COL_RESUMEN = "long_text_mm2kpk90"
COL_NOTAS = "long_text_mm2k8vtc"
COL_ULTIMO_CONTACTO = "date_mm2kmhna"
COL_SINCRONIZADO = "color_mm2kv8c2"
COL_CANAL = "color_mm2kwvp3"
COL_ORIGEN = "text_mm2k5g0c"
COL_NOMBRE_COMPLETO = "text_mm2kz8c6"
COL_PHONE_DEDUPE = "text_mm2kjsap"
REOPEN_STAGE_LABEL = "Conversando"

DEFAULT_STAGE_HIERARCHY = [
    "Nuevo",
    "Conversando",
    "Calificando",
    "Listo para Handoff",
    "Handoff Hecho",
]
DEFAULT_TERMINAL_STAGES = ["Handoff Hecho"]
DEFAULT_SPECIAL_STAGES: list[str] = []
COLUMNS_EXCLUDE_FROM_SYNC: frozenset[str] = frozenset(
    {
        "multiple_person_mm2kdy8q",  # Asignacion - manual
        "long_text_mm2k8vtc",  # Notas - manual
        "pulse_log_mm2kwmcn",  # read-only
        "pulse_updated_mm2kcr4g",  # read-only
    }
)

FSM_STAGE_TO_STAGE_KEY = {
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


def _can_advance_stage(
    current_label: str,
    new_label: str,
    hierarchy: list[str],
    terminal_stages: list[str],
    special_stages: list[str],
) -> bool:
    """
    Devuelve True si el cambio de etapa esta permitido.
    """
    current = current_label.strip()
    new = new_label.strip()

    if new in special_stages:
        return True
    if current in terminal_stages and new == REOPEN_STAGE_LABEL:
        return True
    if new not in hierarchy:
        return True
    if current not in hierarchy:
        return True

    new_index = hierarchy.index(new)
    current_index = hierarchy.index(current)
    return new_index > current_index


def _serialize_column_value(value: object) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _snapshot_lead_columns(
    column_values: dict[str, object],
) -> dict[str, object]:
    """
    Crea snapshot serializado de columnas para comparacion estable.
    """
    return {column_id: _serialize_column_value(value) for column_id, value in column_values.items()}


def _diff_columns(
    current_snapshot: dict[str, object],
    new_columns: dict[str, object],
) -> dict[str, object]:
    """
    Devuelve solo columnas modificadas respecto al snapshot actual.
    """
    if not current_snapshot:
        return new_columns

    changed: dict[str, object] = {}
    for col_id, new_val in new_columns.items():
        new_serialized = _serialize_column_value(new_val)
        current_serialized = _serialize_column_value(current_snapshot.get(col_id))
        if current_serialized != new_serialized:
            changed[col_id] = new_val
    return changed


class MondayCRMAdapter(CRMProvider):
    def __init__(self, api_key: str, board_id: str) -> None:
        normalized_api_key = api_key.strip()
        normalized_board_id = board_id.strip()
        if not normalized_api_key:
            raise ValueError("MONDAY_API_KEY is empty")
        if not normalized_board_id:
            raise ValueError("MONDAY_BOARD_ID is empty")

        self._board_id = int(normalized_board_id)
        self._headers = {
            "Authorization": normalized_api_key,
            "Content-Type": "application/json",
            "API-Version": "2024-01",
        }
        self._stage_map = self._load_stage_map()
        self._field_map = self._load_field_map()
        self._stage_hierarchy = self._load_stage_hierarchy()
        self._terminal_stages = self._load_terminal_stages()
        self._special_stages = self._load_special_stages()

    async def _gql(
        self, query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]:
        payload: dict[str, object] = {"query": query}
        if variables:
            payload["variables"] = variables
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(MONDAY_API_URL, json=payload, headers=self._headers)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Monday GraphQL error: invalid JSON payload")
            if "errors" in result:
                errors = result.get("errors")
                if isinstance(errors, list) and errors:
                    first_error = errors[0]
                    if isinstance(first_error, dict) and "message" in first_error:
                        error_msg = str(first_error["message"])
                    else:
                        error_msg = str(first_error)
                else:
                    error_msg = "unknown error"
                raise ValueError(f"Monday GraphQL error: {error_msg}")
            return result

    async def _find_item_by_phone(self, phone: str) -> str | None:
        normalized_phone = self._normalize_phone(phone)
        if not normalized_phone:
            return None
        query = """
        query($board: ID!, $phone: String!) {
          items_page_by_column_values(
            limit: 1,
            board_id: $board,
            columns: [{column_id: "text_mm2kjsap", column_values: [$phone]}]
          ) { items { id } }
        }
        """
        try:
            data = await self._gql(
                query,
                {"board": str(self._board_id), "phone": normalized_phone},
            )
        except Exception as exc:
            logger.warning(
                "monday_dedup_lookup_failed",
                phone_masked=normalized_phone[:4] + "***",
                reason=str(exc),
            )
            return None
        data_block = data.get("data")
        if not isinstance(data_block, dict):
            return None
        items_page = data_block.get("items_page_by_column_values")
        if not isinstance(items_page, dict):
            return None
        items = items_page.get("items")
        if not isinstance(items, list) or not items:
            return None
        first = items[0]
        if not isinstance(first, dict):
            return None
        item_id = first.get("id")
        if not isinstance(item_id, str):
            return None
        return item_id

    async def upsert_lead(self, lead: Lead) -> str:
        today = date.today().isoformat()
        normalized_phone = self._normalize_phone(lead.phone)
        raw_lead_id = lead.attributes.get("lead_id")
        lead_id = str(raw_lead_id).strip() if raw_lead_id is not None else None
        if not lead_id:
            lead_id = None
        raw_correlation_id = lead.attributes.get("correlation_id")
        correlation_id = str(raw_correlation_id).strip() if raw_correlation_id is not None else None
        if not correlation_id:
            correlation_id = None
        try:
            existing_id = lead.external_id.strip() if isinstance(lead.external_id, str) else None
            if not existing_id:
                raw_monday_id = lead.attributes.get("monday_id")
                if raw_monday_id is not None:
                    monday_id = str(raw_monday_id).strip()
                    existing_id = monday_id or None

            if not existing_id and normalized_phone:
                existing_id = await self._find_item_by_phone(normalized_phone)
                if existing_id:
                    logger.info(
                        "monday_dedup_found",
                        phone_masked=normalized_phone[:4] + "***",
                        item_id=existing_id,
                    )
            resolved_name = self._resolve_lead_name(lead)
            vehicle_interest = self._attr_as_text(lead, "vehicle_interest")
            city = self._attr_as_text(lead, "city")
            budget = self._attr_as_text(lead, "budget")
            fsm_state = self._attr_as_text(lead, "fsm_state")
            summary_text = self._build_summary_text(
                city=city,
                budget=budget,
                vehicle_interest=vehicle_interest,
                fsm_state=fsm_state,
                last_message=self._attr_as_text(lead, "last_message_text"),
            )
            column_values: dict[str, object] = {
                COL_TELEFONO: lead.phone,
                COL_PHONE_DEDUPE: normalized_phone,
                COL_NOMBRE_COMPLETO: resolved_name,
                COL_ORIGEN: lead.source or "WhatsApp Bot",
                COL_VEHICULO: vehicle_interest or "",
                COL_RESUMEN: {"text": summary_text} if summary_text else {"text": ""},
                COL_CANAL: {"label": "WhatsApp Orgánico"},
                COL_SINCRONIZADO: {"label": "Sincronizado"},
                COL_ULTIMO_CONTACTO: {"date": today},
            }
            if fsm_state:
                column_values[COL_ETAPA_BOT] = {"label": self._resolve_stage_label(fsm_state)}
            optional_column_values = self._build_optional_field_columns(
                lead=lead,
                lead_name=resolved_name,
                source=lead.source or "WhatsApp Bot",
                vehicle_interest=vehicle_interest,
                city=city,
                fsm_state=fsm_state,
                base_columns=column_values,
            )
            request_column_values = dict(column_values)
            request_column_values.update(optional_column_values)
            original_keys = list(request_column_values.keys())
            request_column_values = {
                key: value
                for key, value in request_column_values.items()
                if key and value is not None
            }
            removed_columns = sorted(set(original_keys) - set(request_column_values.keys()))
            if removed_columns:
                logger.debug("monday_columns_filtered", removed=removed_columns)
            col_vals = json.dumps(request_column_values)

            if existing_id:
                raw_snapshot = lead.attributes.get("monday_col_snapshot")
                previous_snapshot: dict[str, object] = (
                    raw_snapshot if isinstance(raw_snapshot, dict) else {}
                )
                full_payload = {
                    key: value
                    for key, value in request_column_values.items()
                    if key not in COLUMNS_EXCLUDE_FROM_SYNC
                }
                payload_to_send = _diff_columns(previous_snapshot, full_payload)

                if not payload_to_send:
                    logger.debug(
                        "monday_sync_skipped",
                        reason="no_changes",
                        lead_id=lead_id,
                    )
                    lead.attributes["monday_id"] = existing_id
                    return existing_id

                logger.info(
                    "monday_sync_incremental",
                    columns_changed=sorted(payload_to_send.keys()),
                    columns_total=len(full_payload),
                    lead_id=lead_id,
                )
                logger.info(
                    "monday_op_enqueued",
                    lead_id=lead_id,
                    correlation_id=correlation_id,
                    evento="monday_op_enqueued",
                    resultado="ok",
                    operation="update_item",
                )
                update_col_vals = json.dumps(payload_to_send)
                query = """
                mutation($item: ID!, $board: ID!, $cols: JSON!) {
                  change_multiple_column_values(
                    item_id: $item, board_id: $board, column_values: $cols
                  ) { id }
                }
                """
                try:
                    await self._gql(
                        query,
                        {
                            "item": existing_id,
                            "board": str(self._board_id),
                            "cols": update_col_vals,
                        },
                    )
                except Exception as exc:
                    if optional_column_values and self._is_optional_column_error(exc):
                        fallback_payload = {
                            key: value
                            for key, value in column_values.items()
                            if key not in COLUMNS_EXCLUDE_FROM_SYNC
                        }
                        logger.warning(
                            "monday_optional_columns_ignored",
                            method="upsert_lead",
                            operation="update",
                            optional_columns=sorted(optional_column_values.keys()),
                            error=str(exc),
                        )
                        await self._gql(
                            query,
                            {
                                "item": existing_id,
                                "board": str(self._board_id),
                                "cols": json.dumps(fallback_payload),
                            },
                        )
                    else:
                        raise
                logger.info(
                    "monday_lead_upserted", item_id=existing_id, phone=lead.phone, action="updated"
                )
                lead.attributes["monday_id"] = existing_id
                lead.attributes["monday_col_snapshot"] = _snapshot_lead_columns(full_payload)
                logger.info(
                    "monday_op_ok",
                    lead_id=lead_id,
                    correlation_id=correlation_id,
                    evento="monday_op_ok",
                    resultado="ok",
                    item_id=existing_id,
                )
                return existing_id

            name = resolved_name
            logger.info(
                "monday_op_enqueued",
                lead_id=lead_id,
                correlation_id=correlation_id,
                evento="monday_op_enqueued",
                resultado="ok",
                operation="create_item",
            )
            query = """
            mutation($board: ID!, $name: String!, $cols: JSON!) {
              create_item(
                board_id: $board, item_name: $name, column_values: $cols
              ) { id }
            }
            """
            try:
                data = await self._gql(
                    query, {"board": str(self._board_id), "name": name, "cols": col_vals}
                )
            except Exception as exc:
                if optional_column_values and self._is_optional_column_error(exc):
                    logger.warning(
                        "monday_optional_columns_ignored",
                        method="upsert_lead",
                        operation="create",
                        optional_columns=sorted(optional_column_values.keys()),
                        error=str(exc),
                    )
                    data = await self._gql(
                        query,
                        {
                            "board": str(self._board_id),
                            "name": name,
                            "cols": json.dumps(column_values),
                        },
                    )
                else:
                    raise
            data_block = data.get("data")
            if not isinstance(data_block, dict):
                raise ValueError("Monday create_item response missing data block")
            created_item = data_block.get("create_item")
            if not isinstance(created_item, dict):
                raise ValueError("Monday create_item response missing create_item block")
            item_id = created_item.get("id")
            if not isinstance(item_id, str):
                raise ValueError("Monday create_item response id is invalid")
            logger.info("monday_lead_upserted", item_id=item_id, phone=lead.phone, action="created")
            lead.attributes["monday_id"] = item_id
            logger.info(
                "monday_op_ok",
                lead_id=lead_id,
                correlation_id=correlation_id,
                evento="monday_op_ok",
                resultado="ok",
                item_id=item_id,
            )
            return item_id
        except Exception as exc:
            logger.error(
                "monday_op_error",
                lead_id=lead_id,
                correlation_id=correlation_id,
                evento="monday_op_error",
                resultado="error",
                exc_info=True,
            )
            logger.error(
                "monday_api_error",
                method="upsert_lead",
                phone=lead.phone,
                error=str(exc),
            )
            raise

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Normaliza teléfono a dígitos únicamente."""
        return re.sub(r"\D", "", phone)

    async def change_stage(
        self,
        lead_id: str,
        new_stage: str,
        reason: str | None = None,
        phone: str | None = None,
    ) -> None:
        import json

        label = self._resolve_stage_label(new_stage)
        today = date.today().isoformat()
        monday_id: str | None = None

        if lead_id and str(lead_id).isdigit():
            monday_id = str(lead_id)
        elif phone:
            try:
                monday_id = await self._find_item_by_phone(phone)
            except Exception as exc:
                logger.error("monday_find_item_failed", phone=phone, error=str(exc))
                raise

        if not monday_id:
            logger.error(
                "monday_change_stage_failed_no_item",
                lead_id=lead_id,
                phone=phone,
                new_stage=new_stage,
                reason=reason,
            )
            raise ValueError("monday item not found for stage change")

        try:
            current_stage = await self._get_item_stage_label(monday_id)
            if current_stage and not _can_advance_stage(
                current_label=current_stage,
                new_label=label,
                hierarchy=self._stage_hierarchy,
                terminal_stages=self._terminal_stages,
                special_stages=self._special_stages,
            ):
                logger.warning(
                    "monday_stage_blocked",
                    current=current_stage,
                    attempted=label,
                    reason="hierarchy_violation",
                )
                return

            logger.info(
                "monday_op_enqueued",
                lead_id=lead_id,
                correlation_id=None,
                evento="monday_op_enqueued",
                resultado="ok",
                operation="change_stage",
            )
            query = """
            mutation($item: ID!, $board: ID!, $cols: JSON!) {
              change_multiple_column_values(
                item_id: $item, board_id: $board, column_values: $cols
              ) { id }
            }
            """
            col_vals = json.dumps(
                {
                    COL_ETAPA_BOT: {"label": label},
                    COL_ULTIMO_CONTACTO: {"date": today},
                }
            )
            await self._gql(
                query, {"item": monday_id, "board": str(self._board_id), "cols": col_vals}
            )
            logger.info(
                "monday_stage_changed",
                lead_id=lead_id,
                monday_id=monday_id,
                phone=phone,
                new_stage=new_stage,
                label=label,
            )
            logger.info(
                "monday_op_ok",
                lead_id=lead_id,
                correlation_id=None,
                evento="monday_op_ok",
                resultado="ok",
                item_id=monday_id,
            )
        except Exception as exc:
            logger.error(
                "monday_op_error",
                lead_id=lead_id,
                correlation_id=None,
                evento="monday_op_error",
                resultado="error",
                exc_info=True,
            )
            logger.error(
                "monday_api_error",
                method="change_stage",
                lead_id=lead_id,
                monday_id=monday_id,
                phone=phone,
                error=str(exc),
            )
            raise

    async def _get_item_stage_label(self, item_id: str) -> str | None:
        query = """
        query($item: ID!) {
          items(ids: [$item]) {
            column_values(ids: ["color_mm2kvwdj"]) {
              text
            }
          }
        }
        """
        try:
            data = await asyncio.wait_for(self._gql(query, {"item": item_id}), timeout=5.0)
        except Exception as exc:
            logger.warning(
                "monday_stage_fetch_failed",
                item_id=item_id,
                reason=str(exc),
            )
            return None

        data_block = data.get("data")
        if not isinstance(data_block, dict):
            return None
        items = data_block.get("items")
        if not isinstance(items, list) or not items:
            return None
        first_item = items[0]
        if not isinstance(first_item, dict):
            return None
        column_values = first_item.get("column_values")
        if not isinstance(column_values, list) or not column_values:
            return None
        first_column = column_values[0]
        if not isinstance(first_column, dict):
            return None
        raw_text = first_column.get("text")
        if not isinstance(raw_text, str):
            return None
        text = raw_text.strip()
        return text or None

    async def add_note(self, lead_id: str, note: str, author: str) -> None:
        query = """
        mutation($item: ID!, $body: String!) {
          create_update(item_id: $item, body: $body) { id }
        }
        """
        note_body = f"[{author}]: {note}" if author else note
        try:
            result = await self._gql(
                query,
                {
                    "item": lead_id,
                    "body": note_body,
                },
            )
            update_id: str | None = None
            data_block = result.get("data")
            if isinstance(data_block, dict):
                create_update = data_block.get("create_update")
                if isinstance(create_update, dict):
                    raw_update_id = create_update.get("id")
                    if isinstance(raw_update_id, str):
                        update_id = raw_update_id
            logger.info(
                "monday_note_added",
                item_id=lead_id,
                update_id=update_id,
                lead_id=lead_id,
            )
        except Exception as exc:
            logger.warning(
                "monday_note_failed",
                item_id=lead_id,
                lead_id=lead_id,
                reason=str(exc),
            )

    async def assign_owner(self, lead_id: str, owner_id: str) -> None:
        logger.info("monday_assign_owner_pending", lead_id=lead_id, owner_id=owner_id)

    async def mark_do_not_contact(self, lead_id: str, reason: str) -> None:
        logger.info("monday_do_not_contact_pending", lead_id=lead_id, reason=reason)

    async def schedule_reactivation(self, lead_id: str, not_before: datetime) -> None:
        logger.info("monday_reactivation_pending", lead_id=lead_id, not_before=str(not_before))

    @staticmethod
    def _attr_as_text(lead: Lead, key: str) -> str:
        value = lead.attributes.get(key)
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value)

    @staticmethod
    def _build_summary_text(
        city: str,
        budget: str,
        vehicle_interest: str,
        fsm_state: str,
        last_message: str,
    ) -> str:
        parts: list[str] = []
        if city:
            parts.append(f"Ciudad: {city}")
        if budget:
            parts.append(f"Presupuesto: {budget}")
        if vehicle_interest:
            parts.append(f"Interes: {vehicle_interest}")
        if fsm_state:
            parts.append(f"FSM: {fsm_state}")
        if last_message:
            parts.append(f"Ultimo mensaje: {last_message}")
        return " | ".join(parts)

    @staticmethod
    def _load_stage_map() -> dict[str, str]:
        try:
            return dict(load_brand_config().crm_mapping.stage_map)
        except Exception as exc:
            logger.warning("monday_stage_map_unavailable", error=str(exc), fallback="Nuevo")
            return {}

    @staticmethod
    def _load_stage_hierarchy() -> list[str]:
        return list(DEFAULT_STAGE_HIERARCHY)

    @staticmethod
    def _load_terminal_stages() -> list[str]:
        return list(DEFAULT_TERMINAL_STAGES)

    @staticmethod
    def _load_special_stages() -> list[str]:
        return list(DEFAULT_SPECIAL_STAGES)

    @staticmethod
    def _load_field_map() -> dict[str, str]:
        try:
            return dict(load_brand_config().crm_mapping.field_map)
        except Exception as exc:
            logger.warning("monday_field_map_unavailable", error=str(exc))
            return {}

    def _resolve_stage_label(self, stage: str) -> str:
        normalized = stage.strip()
        stage_key = FSM_STAGE_TO_STAGE_KEY.get(normalized, normalized)
        label = self._stage_map.get(stage_key)
        if label:
            return label

        # If caller already provided a board label, preserve it.
        if normalized in self._stage_map.values():
            return normalized

        logger.warning("monday_stage_label_not_found", stage=stage, fallback="Nuevo")
        return "Nuevo"

    def _build_optional_field_columns(
        self,
        lead: Lead,
        lead_name: str,
        source: str,
        vehicle_interest: str,
        city: str,
        fsm_state: str,
        base_columns: dict[str, object],
    ) -> dict[str, object]:
        source_by_key: dict[str, Any] = {
            "lead_name": lead_name,
            "phone": lead.phone,
            "source": source,
            "vehicle_interest": vehicle_interest,
            "city": city,
            "fsm_state": fsm_state,
        }
        optional_columns: dict[str, object] = {}
        for canonical_key, monday_column_id in self._field_map.items():
            column_id = monday_column_id.strip()
            if not column_id or column_id in base_columns:
                continue

            value = source_by_key.get(canonical_key)
            if value is None:
                continue
            if isinstance(value, str):
                normalized = value.strip()
                if not normalized:
                    continue
                optional_columns[column_id] = normalized
                continue
            optional_columns[column_id] = str(value)
        return optional_columns

    @staticmethod
    def _is_optional_column_error(exc: Exception) -> bool:
        message = str(exc).casefold()
        keywords = (
            "column",
            "label",
            "status",
            "doesn't exist",
            "does not exist",
            "not found",
            "invalid",
        )
        return any(keyword in message for keyword in keywords)

    @staticmethod
    def _resolve_lead_name(lead: Lead) -> str:
        raw_name = lead.name.strip()
        first_message = MondayCRMAdapter._attr_as_text(lead, "last_message_text")
        if raw_name and len(raw_name) >= 3 and raw_name.casefold() != first_message.casefold():
            return raw_name

        suffix = lead.phone[-4:] if lead.phone else "0000"
        return f"Lead {suffix}"
