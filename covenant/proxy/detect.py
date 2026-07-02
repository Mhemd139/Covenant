"""Turn a Layer 0 diff into a quarantine decision.

``detect`` runs the full ``diff.diff_tools`` classifier and keeps only *breaking*
changes — the silent-failure tier — collapsing them to one reason string per tool.
Degraded/compatible changes are intentionally left to pass (they are observable via
``/covenant/status`` but never take a tool offline).
"""

from __future__ import annotations

from .._types import JsonDict
from ..diff import diff_tools


def detect(baseline: list[JsonDict], live: list[JsonDict]) -> dict[str, str]:
    """Return {tool_name: reason} for every tool with a breaking change."""
    reasons: dict[str, list[str]] = {}
    for change in diff_tools(baseline, live):
        if change.tier == "breaking":
            reasons.setdefault(change.tool, []).append(change.message)
    return {tool: "; ".join(msgs) for tool, msgs in reasons.items()}
