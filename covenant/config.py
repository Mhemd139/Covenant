"""Load connection + baseline settings from covenant.toml, with CLI overrides.

A server is reached either over stdio (a ``command`` launched as a subprocess) or
over HTTP (a ``url``). Exactly one must be resolved. A ``--server`` CLI override
wins over the file and is treated as a URL if it looks like one, else a command.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ._types import JsonDict
from .errors import ConfigError

DEFAULT_BASELINE = "covenant.lock.json"


@dataclass
class Config:
    server_command: str | None
    server_url: str | None
    baseline_path: str


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


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

    baseline_path = (data.get("baseline", {}) or {}).get("path", DEFAULT_BASELINE)
    return Config(server_command=command, server_url=url, baseline_path=baseline_path)
