# Covenant — Layer 2: Contract Store (design)

**Date:** 2026-07-01
**Status:** Proposed
**Author:** Aurelius
**Builds on:** Layers 0–1. Reuses `diff`/`contract`/`detect`/`quarantine` unchanged.

## The point of this layer

Give the proxy durable memory. Today quarantine is in-RAM and every proxied call
vanishes. Layer 2 adds a Postgres-backed store so:
- **quarantine survives a restart** (a broken tool stays blocked across proxy
  restarts until its contract is restored),
- **every call is logged** (tool, latency, error, blocked) — the data Layer 4's
  dashboard and metrics read,
- **snapshots + drift are historized** — an audit trail of contract change.

## Core design call: the store is optional and additive

The proxy MUST still run with zero database (Layer 1 unchanged). The store is a
small async interface with two implementations:

- **`InMemoryStore`** (default) — the proxy's current behaviour, now behind the
  interface. No persistence, no deps. Fully unit-tested.
- **`PostgresStore`** (asyncpg, behind an optional `[store]` extra) — same
  interface, JSONB columns. Used when `--database-url` / `DATABASE_URL` is set.

`covenant proxy` picks the store: Postgres if a URL is given, else in-memory. This
keeps the core linter and the standalone proxy dependency-light, and lets the store
be tested without infra (in-memory) *and* with it (Postgres integration).

## Interface (`covenant/store/base.py`)

```python
class Store(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def record_call(self, tool, method, latency_ms, is_error, blocked) -> None: ...
    async def record_drift(self, tool, severity, changes: list[dict]) -> None: ...
    async def set_status(self, tool, status, reason) -> None: ...
    async def load_quarantine(self) -> dict[str, str]: ...   # tool -> reason, for restart
    async def recent_calls(self, limit) -> list[dict]: ...
```

`sync_quarantine(breaking: dict)` on the store persists the full current set
(mirrors `Quarantine.sync`), so a restored tool is cleared in the DB too.

## Schema (`covenant/store/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS tool_status (
    tool TEXT PRIMARY KEY,
    status TEXT NOT NULL,             -- 'ok' | 'quarantined'
    reason TEXT,
    since TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS drift_events (
    id BIGSERIAL PRIMARY KEY,
    tool TEXT NOT NULL,
    severity TEXT NOT NULL,           -- 'breaking' | 'degraded'
    changes JSONB NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS calls (
    id BIGSERIAL PRIMARY KEY,
    tool TEXT,
    method TEXT,
    latency_ms INTEGER,
    is_error BOOLEAN NOT NULL DEFAULT false,
    blocked BOOLEAN NOT NULL DEFAULT false,
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS calls_at_idx ON calls (at DESC);
```

Snapshots history is deferred to when it's actually consumed (Layer 3/4); the
committed `covenant.lock.json` remains the baseline of record. Recording it here
now would be storage without a reader — added when a reader exists.

## Proxy wiring (additive, in `proxy/server.py`)

- `create_app(..., store=None)` — defaults to `InMemoryStore`.
- On every proxied `tools/call`: `await store.record_call(...)` with latency +
  whether it was blocked (quarantine short-circuit) or errored.
- On `POST /covenant/refresh`: after `detect`, `await store.sync_quarantine(...)`
  and `record_drift` for each breaking tool.
- On startup (Postgres): `load_quarantine()` seeds the in-RAM `Quarantine`, so a
  restart resumes blocking without waiting for the first refresh.
- New `GET /covenant/calls?limit=` returns `recent_calls` (feeds Layer 4).

Recording is best-effort and must never break proxying: a store error is logged,
not raised into the request path (a firewall that fails open on its own telemetry
is correct; one that drops traffic because logging hiccuped is not).

## Infra: `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: covenant, POSTGRES_PASSWORD: covenant, POSTGRES_DB: covenant }
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes: { pgdata: {} }
```

`DATABASE_URL = postgresql://covenant:covenant@127.0.0.1:5432/covenant`. Reversible:
`docker compose down -v` removes it entirely.

## Testing (TDD)

1. **`test_memory_store.py`** — full `InMemoryStore`: record calls/drift/status,
   `load_quarantine` round-trip, `recent_calls` ordering + limit. Pure, fast.
2. **`test_store_postgres.py`** — integration against the compose Postgres, applies
   `schema.sql`, round-trips each table. `skipif` when `COVENANT_TEST_DB` is unset,
   so the suite stays green with no infra and is fully exercised with it. This is
   the honest coverage line — stated, not hidden.
3. **`test_proxy_store.py`** — proxy + `InMemoryStore` via TestClient: a healthy
   call and a blocked call are both recorded with the right `blocked` flag.

## Deliberately NOT in this layer

- No ORM — plain asyncpg + SQL. No migration framework — one idempotent `schema.sql`.
- No snapshot-history table yet (no reader). No metrics/dashboard (Layer 4).
- Store failures never fail the proxy request path.
```
