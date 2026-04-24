from datetime import date

import httpx
import structlog

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

STAGE_LABELS = {
    "greeting": "Nuevo",
    "discovery": "Conversando",
    "qualification": "Calificando",
    "catalog_navigation": "Calificando",
    "document_delivery": "Listo para Handoff",
    "appointment": "Listo para Handoff",
    "handoff": "Handoff Hecho",
    "closing": "Handoff Hecho",
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

    async def _gql(self, query: str, variables: dict | None = None) -> dict:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(MONDAY_API_URL, json=payload, headers=self._headers)
            response.raise_for_status()
            result = response.json()
            if "errors" in result:
                error_msg = result["errors"][0]["message"]
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
        items = data.get("data", {}).get("items_page_by_column_values", {}).get("items", [])
        return items[0]["id"] if items else None

    async def upsert_lead(self, lead: Lead) -> str:
        import json

        today = date.today().isoformat()
        try:
            existing_id = await self._find_item_by_phone(lead.phone)
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
                COL_NOMBRE_COMPLETO: lead.name or "",
                COL_ORIGEN: lead.source or "WhatsApp Bot",
                COL_VEHICULO: vehicle_interest or "",
                COL_RESUMEN: {"text": summary_text} if summary_text else {"text": ""},
                COL_CANAL: {"label": "WhatsApp Orgánico"},
                COL_SINCRONIZADO: {"label": "Sincronizado"},
                COL_ULTIMO_CONTACTO: {"date": today},
            }
            if fsm_state:
                column_values[COL_ETAPA_BOT] = {"label": STAGE_LABELS.get(fsm_state, fsm_state)}
            col_vals = json.dumps(column_values)

            if existing_id:
                query = """
                mutation($item: ID!, $board: ID!, $cols: JSON!) {
                  change_multiple_column_values(
                    item_id: $item, board_id: $board, column_values: $cols
                  ) { id }
                }
                """
                await self._gql(
                    query, {"item": existing_id, "board": str(self._board_id), "cols": col_vals}
                )
                logger.info(
                    "monday_lead_upserted", item_id=existing_id, phone=lead.phone, action="updated"
                )
                return existing_id

            name = lead.name or lead.phone
            query = """
            mutation($board: ID!, $name: String!, $cols: JSON!) {
              create_item(
                board_id: $board, item_name: $name, column_values: $cols
              ) { id }
            }
            """
            data = await self._gql(
                query, {"board": str(self._board_id), "name": name, "cols": col_vals}
            )
            item_id = data["data"]["create_item"]["id"]
            logger.info("monday_lead_upserted", item_id=item_id, phone=lead.phone, action="created")
            return item_id
        except Exception as exc:
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

        label = STAGE_LABELS.get(new_stage, new_stage)
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
        except Exception as exc:
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

    async def schedule_reactivation(self, lead_id: str, not_before) -> None:
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
