"""In-memory quarantine state: which tools are blocked, and why.

Two buckets. The **schema** bucket is owned by ``detect()``: ``sync`` replaces it
wholesale from a fresh detection pass (the in-band ``tools/list`` sync and the store
restore at startup both go through it). The **response** bucket is owned by the
per-call verifier and is untouched by ``sync`` — a response-caught liar whose schema
is clean must not be released seconds later by a client connect. Only
``clear_responses`` (the refresh path) empties it.

Deliberately not persisted — Layer 2 (Postgres) owns durability for the schema
bucket; the response bucket re-arms on the next violating call after a restart.
"""

from __future__ import annotations


class Quarantine:
    def __init__(self) -> None:
        self._schema: dict[str, str] = {}
        self._response: dict[str, str] = {}

    def mark(self, tool: str, reason: str) -> None:
        self._schema[tool] = reason

    def mark_response(self, tool: str, reason: str) -> None:
        self._response[tool] = reason

    def clear(self, tool: str) -> None:
        self._schema.pop(tool, None)
        self._response.pop(tool, None)

    def clear_responses(self) -> None:
        """Refresh is the operator's re-check button: release response-caught tools."""
        self._response.clear()

    def is_quarantined(self, tool: str) -> bool:
        return tool in self._schema or tool in self._response

    def reason(self, tool: str) -> str | None:
        return self._schema.get(tool) or self._response.get(tool)

    def all(self) -> dict[str, str]:
        return {**self._response, **self._schema}

    def sources(self) -> dict[str, str]:
        """Which bucket(s) hold each quarantined tool — surfaced on /covenant/status."""
        out = {tool: "schema" for tool in self._schema}
        for tool in self._response:
            out[tool] = "schema+response" if tool in out else "response"
        return out

    def sync(self, breaking: dict[str, str]) -> None:
        """Replace the schema bucket with the current breaking tools (tool -> reason)."""
        self._schema = dict(breaking)
