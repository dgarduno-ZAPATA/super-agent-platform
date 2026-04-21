from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import StringIO

import httpx
import structlog

from core.domain.branch import Branch
from core.ports.branch_provider import BranchProvider

logger = structlog.get_logger("super_agent_platform.adapters.branches.sheets_adapter")


@dataclass(slots=True)
class _BranchAccumulator:
    sucursal_key: str
    display_name: str
    centro_sheet: str
    phones: list[str] = field(default_factory=list)


class SheetsBranchAdapter(BranchProvider):
    def __init__(
        self,
        csv_url: str,
        cache_ttl_seconds: int = 600,
        http_get: Callable[[str], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._csv_url = csv_url
        self._cache_ttl_seconds = cache_ttl_seconds
        self._http_get = http_get or self._default_http_get
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._cached_branches: list[Branch] = []
        self._cache_expires_at: datetime | None = None

    def list_branches(self) -> list[Branch]:
        now = self._now_provider()
        if self._cache_expires_at is not None and now < self._cache_expires_at:
            return self._cached_branches

        try:
            branches = self._load_from_sheet()
            self._cached_branches = branches
            self._cache_expires_at = now + timedelta(seconds=self._cache_ttl_seconds)
            return branches
        except Exception:
            logger.warning(
                "branch_sheet_read_failed_using_cache",
                branch_sheet_url=self._csv_url,
                has_cached_data=bool(self._cached_branches),
            )
            return self._cached_branches

    def get_branch_by_centro(self, centro: str) -> Branch | None:
        normalized = centro.strip().casefold()
        if not normalized:
            return None

        for branch in self.list_branches():
            if branch.centro_sheet.strip().casefold() == normalized:
                return branch
        return None

    def get_branch_by_key(self, key: str) -> Branch | None:
        normalized = key.strip().casefold()
        if not normalized:
            return None

        for branch in self.list_branches():
            if branch.sucursal_key.strip().casefold() == normalized:
                return branch
        return None

    def _load_from_sheet(self) -> list[Branch]:
        rows = self._parse_csv_rows(self._http_get(self._csv_url))
        grouped: dict[str, _BranchAccumulator] = {}
        order: list[str] = []

        for row in rows:
            if not self._is_active(row.get("activa", "")):
                continue

            sucursal_key = str(row.get("sucursal_key", "")).strip()
            if not sucursal_key:
                continue

            accumulator = grouped.get(sucursal_key)
            if accumulator is None:
                accumulator = _BranchAccumulator(
                    sucursal_key=sucursal_key,
                    display_name=str(row.get("display_name", "")).strip(),
                    centro_sheet=str(row.get("centro_sheet", "")).strip(),
                )
                grouped[sucursal_key] = accumulator
                order.append(sucursal_key)

            raw_phone = str(row.get("telefono_encargado", "")).strip()
            if raw_phone and raw_phone not in accumulator.phones:
                accumulator.phones.append(raw_phone)

        branches: list[Branch] = []
        for key in order:
            item = grouped[key]
            branches.append(
                Branch(
                    sucursal_key=item.sucursal_key,
                    display_name=item.display_name,
                    centro_sheet=item.centro_sheet,
                    phones=item.phones,
                    activa=True,
                )
            )
        return branches

    @staticmethod
    def _default_http_get(url: str) -> str:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
        reader = csv.DictReader(StringIO(csv_text))
        return [dict(row) for row in reader]

    @staticmethod
    def _is_active(value: str) -> bool:
        return value.strip().casefold() in {"true", "1", "yes", "si", "sí"}
