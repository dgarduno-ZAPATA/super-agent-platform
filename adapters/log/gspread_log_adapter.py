from __future__ import annotations

import asyncio
import json
import os

import gspread
import structlog
from gspread.worksheet import Worksheet

from core.ports.conversation_log import ConversationLogPort

logger = structlog.get_logger("super_agent_platform.adapters.log.gspread_log_adapter")

CONVERSATION_LOG_SHEET_URL_ENV = "CONVERSATION_LOG_SHEET_URL"
GOOGLE_CREDENTIALS_JSON_ENV = "GOOGLE_CREDENTIALS_JSON"
GOOGLE_APPLICATION_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"

_HEADERS = [
    "lead_id",
    "phone_masked",
    "last_state",
    "last_intent",
    "summary",
    "updated_at",
    "correlation_id",
]


class GspreadLogAdapter(ConversationLogPort):
    def __init__(self) -> None:
        self._client: gspread.Client | None = None
        self._worksheet: Worksheet | None = None
        self._sheet_url = os.getenv(CONVERSATION_LOG_SHEET_URL_ENV, "").strip()
        self._init_lock = asyncio.Lock()

    async def log_turn(
        self,
        lead_id: str | None,
        phone_masked: str,
        last_state: str,
        last_intent: str,
        summary: str,
        updated_at: str,
        correlation_id: str | None = None,
    ) -> None:
        row_lead_id = lead_id if lead_id is not None else "unknown"
        row_values = [
            row_lead_id,
            phone_masked,
            last_state,
            last_intent,
            summary,
            updated_at,
            correlation_id or "",
        ]

        try:
            worksheet = await self._get_worksheet()
            await asyncio.to_thread(self._ensure_headers, worksheet)

            if lead_id is None:
                await asyncio.to_thread(worksheet.append_row, row_values, "USER_ENTERED")
                return

            existing_rows = await asyncio.to_thread(worksheet.col_values, 1)
            row_index: int | None = None
            # row 1 is header.
            for index, value in enumerate(existing_rows[1:], start=2):
                if value.strip() == row_lead_id:
                    row_index = index
                    break

            if row_index is None:
                await asyncio.to_thread(worksheet.append_row, row_values, "USER_ENTERED")
                return

            await asyncio.to_thread(
                worksheet.update,
                f"A{row_index}:G{row_index}",
                [row_values],
                "USER_ENTERED",
            )
        except Exception as exc:
            logger.error(
                "conversation_log_failed",
                lead_id=lead_id,
                reason=str(exc),
                exc_info=True,
            )

    async def _get_worksheet(self) -> Worksheet:
        if self._worksheet is not None:
            return self._worksheet

        async with self._init_lock:
            if self._worksheet is not None:
                return self._worksheet

            if not self._sheet_url:
                raise ValueError(
                    f"{CONVERSATION_LOG_SHEET_URL_ENV} is missing; cannot write conversation log"
                )

            client = self._client or self._build_client()
            spreadsheet = await asyncio.to_thread(client.open_by_url, self._sheet_url)
            worksheet = await asyncio.to_thread(spreadsheet.sheet1)
            self._client = client
            self._worksheet = worksheet
            return worksheet

    def _build_client(self) -> gspread.Client:
        credentials_json = os.getenv(GOOGLE_CREDENTIALS_JSON_ENV, "").strip()
        if credentials_json:
            credentials = json.loads(credentials_json)
            return gspread.service_account_from_dict(credentials)

        credentials_path = os.getenv(GOOGLE_APPLICATION_CREDENTIALS_ENV, "").strip()
        if credentials_path:
            return gspread.service_account(filename=credentials_path)

        credentials, _ = gspread.auth.default()
        return gspread.authorize(credentials)

    @staticmethod
    def _ensure_headers(worksheet: Worksheet) -> None:
        current_headers = worksheet.row_values(1)
        if current_headers[: len(_HEADERS)] == _HEADERS:
            return
        worksheet.update("A1:G1", [_HEADERS], "USER_ENTERED")
