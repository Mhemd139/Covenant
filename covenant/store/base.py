"""The Store interface — what the proxy needs from durable memory.

Any object satisfying this Protocol can back the proxy. Kept deliberately small:
quarantine persistence, a call log, and a drift log. Recording is best-effort and
must never break the request path (see the proxy wiring).
"""

from __future__ import annotations

from typing import Protocol

from .._types import JsonDict


class Store(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    async def sync_quarantine(self, breaking: dict[str, str]) -> None: ...
    async def load_quarantine(self) -> dict[str, str]: ...

    async def record_call(
        self, tool: str | None, method: str | None, latency_ms: int, is_error: bool, blocked: bool
    ) -> None: ...
    async def record_drift(self, tool: str, severity: str, changes: list[JsonDict]) -> None: ...

    async def recent_calls(self, limit: int) -> list[JsonDict]: ...
    async def recent_drift(self, limit: int) -> list[JsonDict]: ...
