"""In-memory quarantine state: which tools are blocked, and why.

Deliberately not persisted — Layer 2 (Postgres) owns durability. ``sync`` replaces
the whole set from a fresh detection pass, so a tool whose contract is restored is
released automatically on the next refresh.
"""

from __future__ import annotations


class Quarantine:
    def __init__(self) -> None:
        self._reasons: dict[str, str] = {}

    def mark(self, tool: str, reason: str) -> None:
        self._reasons[tool] = reason

    def clear(self, tool: str) -> None:
        self._reasons.pop(tool, None)

    def is_quarantined(self, tool: str) -> bool:
        return tool in self._reasons

    def reason(self, tool: str) -> str | None:
        return self._reasons.get(tool)

    def all(self) -> dict[str, str]:
        return dict(self._reasons)

    def sync(self, breaking: dict[str, str]) -> None:
        """Replace the quarantine set with the current breaking tools (tool -> reason)."""
        self._reasons = dict(breaking)
