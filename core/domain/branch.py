from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Branch:
    sucursal_key: str
    display_name: str
    centro_sheet: str
    phones: list[str]
    activa: bool
