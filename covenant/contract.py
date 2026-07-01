"""The contract model: capture MCP tool definitions and (de)serialize the baseline.

A ``ToolContract`` is one tool's ``(description, inputSchema, outputSchema)`` plus a
``schema_hash`` — a *schema*-identity hash (description deliberately excluded; see
the Layer 0 design spec). The baseline file is deterministic (sorted keys, no
timestamp) so an unchanged server re-snapshots to a byte-identical file.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ._types import JsonDict
from .errors import BaselineError

BASELINE_VERSION = "0.1.0"


@dataclass
class ToolContract:
    name: str
    description: str | None
    input_schema: JsonDict | None
    output_schema: JsonDict | None
    schema_hash: str


def _canonical(schema: JsonDict | None) -> str:
    return json.dumps(schema or {}, sort_keys=True, separators=(",", ":"))


def schema_hash(input_schema: JsonDict | None, output_schema: JsonDict | None) -> str:
    h = hashlib.sha256()
    h.update(_canonical(input_schema).encode())
    h.update(b"|")
    h.update(_canonical(output_schema).encode())
    return f"sha256:{h.hexdigest()}"


def contract_from_tool(tool: JsonDict) -> ToolContract:
    """Build a ToolContract from an MCP wire-shape tool dict."""
    inp = tool.get("inputSchema")
    out = tool.get("outputSchema")
    return ToolContract(
        name=tool["name"],
        description=tool.get("description"),
        input_schema=inp,
        output_schema=out,
        schema_hash=schema_hash(inp, out),
    )


def to_baseline(contracts: list[ToolContract], server: str) -> JsonDict:
    return {
        "covenant_version": BASELINE_VERSION,
        "server": server,
        "tools": {
            c.name: {
                "description": c.description,
                "inputSchema": c.input_schema,
                "outputSchema": c.output_schema,
                "schema_hash": c.schema_hash,
            }
            for c in contracts
        },
    }


def write_baseline(path: str | Path, contracts: list[ToolContract], server: str) -> None:
    data = to_baseline(contracts, server)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    Path(path).write_text(text, encoding="utf-8")


def read_baseline(path: str | Path) -> tuple[str, list[JsonDict]]:
    """Read a baseline file; return (server, tools) where tools are wire-shape dicts."""
    p = Path(path)
    if not p.exists():
        raise BaselineError(f"baseline not found: {p} (run `covenant snapshot` first)")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BaselineError(f"baseline is not valid JSON: {p} ({e})") from e

    tools = [
        {
            "name": name,
            "description": t.get("description"),
            "inputSchema": t.get("inputSchema"),
            "outputSchema": t.get("outputSchema"),
        }
        for name, t in (data.get("tools") or {}).items()
    ]
    return data.get("server", ""), tools
