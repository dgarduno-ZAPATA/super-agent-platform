from __future__ import annotations

from typing import Protocol

from core.domain.branch import Branch


class BranchProvider(Protocol):
    def list_branches(self) -> list[Branch]:
        """Return active branches available for routing."""

    def get_branch_by_centro(self, centro: str) -> Branch | None:
        """Return one active branch by centro identifier, if it exists."""

    def get_branch_by_key(self, key: str) -> Branch | None:
        """Return one active branch by business key, if it exists."""
