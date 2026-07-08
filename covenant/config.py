"""Load connection + baseline + probe settings from covenant.toml, with CLI overrides.

A server is reached either over stdio (a ``command`` launched as a subprocess) or
over HTTP (a ``url``). Exactly one must be resolved. A ``--server`` CLI override
wins over the file and is treated as a URL if it looks like one, else a command.

``[[probes]]`` entries are Layer 3's behavioral probes: example calls (tool + args)
that snapshot/check will *execute* against the server — only list read-only tools.
An optional ``expect`` table pins exact output values; a pinned field that comes
back missing or unequal at check time is BREAKING (see diff.diff_expect).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ._types import JsonDict
from .errors import ConfigError

DEFAULT_BASELINE = "covenant.lock.json"


@dataclass
class Probe:
    tool: str
    args: JsonDict
    expect: JsonDict = field(default_factory=dict)


@dataclass
class Config:
    server_command: str | None
    server_url: str | None
    baseline_path: str
    probes: list[Probe] = field(default_factory=list)
    judge_model: str | None = None


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _parse_probes(data: JsonDict) -> list[Probe]:
    probes: list[Probe] = []
    for i, entry in enumerate(data.get("probes") or []):
        tool = entry.get("tool") if isinstance(entry, dict) else None
        args = entry.get("args", {}) if isinstance(entry, dict) else None
        expect = entry.get("expect", {}) if isinstance(entry, dict) else None
        if (not isinstance(tool, str) or not tool
                or not isinstance(args, dict) or not isinstance(expect, dict)):
            raise ConfigError(
                f'probe #{i + 1} is invalid: each [[probes]] needs tool = "name" '
                "and optional args / expect tables"
            )
        probes.append(Probe(tool=tool, args=args, expect=expect))
    return probes


def load_config(path: str | Path = "covenant.toml", server_override: str | None = None) -> Config:
    p = Path(path)
    data: JsonDict = {}
    if p.exists():
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"invalid config {p}: {e}") from e
    elif server_override is None:
        raise ConfigError(f"config not found: {p} (create covenant.toml or pass --server)")

    server = data.get("server", {})
    command = server.get("command")
    url = server.get("url")

    if server_override is not None:
        if _looks_like_url(server_override):
            command, url = None, server_override
        else:
            command, url = server_override, None

    if not command and not url:
        raise ConfigError("no server configured: set [server].command or .url, or pass --server")

    judge = data.get("judge") or {}
    if not isinstance(judge, dict):
        raise ConfigError("[judge] must be a table")
    judge_model = judge.get("model")
    if judge_model is not None and not isinstance(judge_model, str):
        raise ConfigError("[judge].model must be a string")

    baseline_path = (data.get("baseline", {}) or {}).get("path", DEFAULT_BASELINE)
    return Config(
        server_command=command,
        server_url=url,
        baseline_path=baseline_path,
        probes=_parse_probes(data),
        judge_model=judge_model,
    )
