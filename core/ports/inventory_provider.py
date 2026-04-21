from __future__ import annotations

from typing import Protocol


class InventoryProvider(Protocol):
    def get_products(self) -> list[dict[str, object]]:
        """Return available inventory products."""

    def search_products(self, query: str) -> list[dict[str, object]]:
        """Search inventory products by free-text query."""
