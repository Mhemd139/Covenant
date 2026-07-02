"""In-memory Store: the proxy's default when no database is configured.

Same interface as PostgresStore, so the proxy is store-agnostic. State is lost on
restart — that is the whole reason Layer 2 also ships PostgresStore.
"""

from __future__ import annotations

from .._types import JsonDict


class InMemoryStore:
    def __init__(self) -> None:
        self._status: dict[str, tuple[str, str | None]] = {}
        self._calls: list[JsonDict] = []
        self._drift: list[JsonDict] = []

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def set_status(self, tool: str, status: str, reason: str | None) -> None:
        self._status[tool] = (status, reason)

    async def sync_quarantine(self, breaking: dict[str, str]) -> None:
        # Match PostgresStore: clear only quarantined entries, preserve any other
        # statuses set via set_status, then apply the new quarantine set.
        self._status = {
            tool: st for tool, st in self._status.items() if st[0] != "quarantined"
        }
        self._status.update(
            {tool: ("quarantined", reason) for tool, reason in breaking.items()}
        )

    async def load_quarantine(self) -> dict[str, str]:
        return {
            tool: (reason or "")
            for tool, (status, reason) in self._status.items()
            if status == "quarantined"
        }

    async def record_call(
        self, tool: str | None, method: str | None, latency_ms: int, is_error: bool, blocked: bool
    ) -> None:
        self._calls.append({
            "tool": tool, "method": method, "latency_ms": latency_ms,
            "is_error": is_error, "blocked": blocked,
        })

    async def record_drift(self, tool: str, severity: str, changes: list[JsonDict]) -> None:
        self._drift.append({"tool": tool, "severity": severity, "changes": changes})

    async def recent_calls(self, limit: int) -> list[JsonDict]:
        return list(reversed(self._calls))[:limit]

    async def recent_drift(self, limit: int) -> list[JsonDict]:
        return list(reversed(self._drift))[:limit]
