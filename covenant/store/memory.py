"""In-memory Store: the proxy's default when no database is configured.

Same interface as PostgresStore, so the proxy is store-agnostic. State is lost on
restart — that is the whole reason Layer 2 also ships PostgresStore.
"""

from __future__ import annotations

from collections import deque

from .._types import JsonDict

_LOG_CAP = 1000  # the proxy runs indefinitely; an unbounded in-memory log is a leak


class InMemoryStore:
    def __init__(self) -> None:
        self._quarantine: dict[str, str] = {}
        self._calls: deque[JsonDict] = deque(maxlen=_LOG_CAP)
        self._drift: deque[JsonDict] = deque(maxlen=_LOG_CAP)

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def sync_quarantine(self, breaking: dict[str, str]) -> None:
        self._quarantine = dict(breaking)

    async def load_quarantine(self) -> dict[str, str]:
        return dict(self._quarantine)

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
