"""Contract snapshot capture: turn MCP tool definitions into stored snapshots.

A snapshot is the pair (inputSchema, outputSchema) for a tool plus a stable hash.
The first snapshot seen for a tool becomes its baseline; later snapshots are the
"current" contract that drift detection diffs against the baseline.
"""

import hashlib
import json

from . import db


def _canonical(schema) -> str:
    return json.dumps(schema or {}, sort_keys=True, separators=(",", ":"))


def schema_hash(input_schema, output_schema) -> str:
    h = hashlib.sha256()
    h.update(_canonical(input_schema).encode())
    h.update(b"|")
    h.update(_canonical(output_schema).encode())
    return h.hexdigest()


def normalize_tool(t) -> dict:
    """Accept either a wire-JSON tool dict or an mcp ClientSession Tool object."""
    if isinstance(t, dict):
        return {
            "name": t.get("name"),
            "inputSchema": t.get("inputSchema"),
            "outputSchema": t.get("outputSchema"),
        }
    return {
        "name": t.name,
        "inputSchema": getattr(t, "inputSchema", None),
        "outputSchema": getattr(t, "outputSchema", None),
    }


async def capture_tools(pool, tools: list[dict]) -> list[dict]:
    """Persist a snapshot per tool. Returns per-tool capture metadata."""
    captured = []
    for t in tools:
        name = t["name"]
        if not name:
            continue
        inp, out = t.get("inputSchema"), t.get("outputSchema")
        digest = schema_hash(inp, out)
        baseline = await db.get_baseline(pool, name)
        is_baseline = baseline is None
        await db.insert_snapshot(pool, name, inp, out, digest, is_baseline)
        captured.append({"tool": name, "hash": digest, "baseline": is_baseline})
    return captured
