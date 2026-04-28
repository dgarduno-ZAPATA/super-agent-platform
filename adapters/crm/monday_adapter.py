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
        query = """
        query($board: ID!, $phone: String!) {
          items_page_by_column_values(
            limit: 1,
            board_id: $board,
            columns: [{column_id: "text_mm2k3epp", column_values: [$phone]}]
          ) { items { id } }
        }
        """
        data = await self._gql(query, {"board": str(self._board_id), "phone": phone})
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
        import json

        today = date.today().isoformat()
        raw_lead_id = lead.attributes.get("lead_id")
        lead_id = str(raw_lead_id).strip() if raw_lead_id is not None else None
        if not lead_id:
            lead_id = None
        raw_correlation_id = lead.attributes.get("correlation_id")
        correlation_id = str(raw_correlation_id).strip() if raw_correlation_id is not None else None
        if not correlation_id:
            correlation_id = None
        try:
            existing_id = await self._find_item_by_phone(lead.phone)
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
            col_vals = json.dumps(request_column_values)

            if existing_id:
                logger.info(
                    "monday_op_enqueued",
                    lead_id=lead_id,
                    correlation_id=correlation_id,
                    evento="monday_op_enqueued",
                    resultado="ok",
                    operation="update_item",
                )
                query = """
                mutation($item: ID!, $board: ID!, $cols: JSON!) {
                  change_multiple_column_values(
                    item_id: $item, board_id: $board, column_values: $cols
                  ) { id }
                }
                """
                try:
                    await self._gql(
                        query, {"item": existing_id, "board": str(self._board_id), "cols": col_vals}
                    )
                except Exception as exc:
                    if optional_column_values and self._is_optional_column_error(exc):
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
                                "cols": json.dumps(column_values),
                            },
                        )
                    else:
                        raise
                logger.info(
                    "monday_lead_upserted", item_id=existing_id, phone=lead.phone, action="updated"
                )
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

    async def add_note(self, lead_id: str, note: str, author: str) -> None:
        import json

        try:
            query = """
            mutation($item: ID!, $board: ID!, $col: String!, $val: JSON!) {
              change_column_value(
                item_id: $item, board_id: $board,
                column_id: $col, value: $val
              ) { id }
            }
            """
            await self._gql(
                query,
                {
                    "item": lead_id,
                    "board": str(self._board_id),
                    "col": COL_NOTAS,
                    "val": json.dumps({"text": f"[{author}]: {note}"}),
                },
            )
            logger.info("monday_note_added", lead_id=lead_id, author=author)
        except Exception as exc:
            logger.error("monday_api_error", method="add_note", lead_id=lead_id, error=str(exc))
            raise

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
