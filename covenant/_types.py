"""Shared type aliases.

MCP tool definitions and JSON Schemas are heterogeneous JSON objects, so a precise
``TypedDict`` would fight the data. ``JsonDict`` names that intent in one place.
"""

from __future__ import annotations

from typing import Any

JsonDict = dict[str, Any]
