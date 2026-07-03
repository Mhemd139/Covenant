"""Pure reconcile logic for an MCPContract: is a check due, and what did it find.

Everything here is cluster-free — kopf and the kubernetes client stay in
``handlers.py``. A check reuses the Layer 0/3 pipeline verbatim: introspect the
server, diff against the baseline, re-run baselined probes. Errors never
propagate: a failed check becomes ``result: error`` in the CR status, because an
operator must not crash-loop on one unreachable server.
"""

from __future__ import annotations

from datetime import datetime

from .._types import JsonDict
from ..config import Config, Probe
from ..contract import parse_baseline
from ..diff import diff_probes, diff_tools
from ..errors import CovenantError
from ..introspect import introspect, run_probes

DEFAULT_INTERVAL_S = 300


def due(last_check_iso: str | None, interval_s: int, now: datetime) -> bool:
    """True when the contract has never been checked or its interval has elapsed."""
    if not last_check_iso:
        return True
    try:
        last = datetime.fromisoformat(last_check_iso)
    except ValueError:
        return True  # unreadable timestamp: re-check rather than stall forever
    return (now - last).total_seconds() >= interval_s


def check_contract(server_url: str, baseline_text: str, now: datetime) -> JsonDict:
    """Run one contract check; always return a status patch, never raise."""
    status: JsonDict = {"lastCheckTime": now.isoformat()}
    try:
        _, base_tools, base_probes = parse_baseline(baseline_text, source="configmap")
        cfg = Config(server_command=None, server_url=server_url, baseline_path="")
        changes = diff_tools(base_tools, introspect(cfg))
        if base_probes:
            probes = [Probe(tool=p["tool"], args=p.get("args") or {}) for p in base_probes]
            changes += diff_probes(base_probes, run_probes(cfg, probes))
    except CovenantError as e:
        status.update({"result": "error", "message": str(e)})
        return status

    counts = {"breaking": 0, "degraded": 0, "compatible": 0}
    for c in changes:
        counts[c.tier] = counts.get(c.tier, 0) + 1
    if counts["breaking"]:
        result = "breaking"
    elif counts["degraded"]:
        result = "degraded"
    else:
        result = "clean"
    status.update({
        "result": result,
        **counts,
        "message": "; ".join(c.message for c in changes[:5]) or "contract matches the baseline",
    })
    return status
