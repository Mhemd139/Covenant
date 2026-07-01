"""Layer 2 — durable memory for the proxy.

A small async ``Store`` interface with two implementations: ``InMemoryStore`` (the
proxy's default, no deps) and ``PostgresStore`` (asyncpg, optional ``[store]`` extra).
The proxy runs fully without a database; a store only adds persistence.
"""

from .base import Store

__all__ = ["Store"]
