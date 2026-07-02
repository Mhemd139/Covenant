"""Typed errors so the CLI can fail with clear messages and exit codes."""

from __future__ import annotations


class CovenantError(Exception):
    """Base class for all Covenant errors."""


class ConfigError(CovenantError):
    """The covenant config file is missing or invalid."""


class ConnectionError(CovenantError):
    """Could not connect to or introspect the MCP server."""


class BaselineError(CovenantError):
    """The baseline file is missing or malformed."""
