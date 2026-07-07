# Covenant — project instructions

Covenant (`covenant-mcp`) is a contract linter for MCP servers: snapshot tool schemas to a committed baseline (`covenant.lock.json`), diff the live server against it, classify every change BREAKING / DEGRADED / COMPATIBLE, and optionally enforce quarantine at a transparent reverse-proxy.

## Commands

```bash
pip install -e ".[dev]"        # everything: core + proxy + store + tooling
pytest                          # Postgres tests skip unless COVENANT_TEST_DB is set
ruff check . && mypy covenant   # both must pass; mypy is strict
covenant check                  # lint the example server against the committed baseline
COVENANT_DRIFT=1 covenant check # inject a real breaking change; must exit 1
COVENANT_BEHAVIOR_DRIFT=1 covenant check # body-only drift (schema identical); probes must catch it, exit 1
COVENANT_SEMANTIC_DRIFT=1 covenant check # value-only drift (schema AND shape identical); expect pins must catch it, exit 1
```

- `covenant` spawns the stdio server with `python` from PATH — the venv must be active (or its Scripts dir on PATH) or introspection fails with `ModuleNotFoundError: mcp`.
- Postgres tests: `docker compose up -d db`, then `COVENANT_TEST_DB=postgresql://covenant:covenant@127.0.0.1:5432/covenant pytest`.

## Architecture (dependency-ordered layers)

| Layer | Where | Rule |
|---|---|---|
| 0 contract core | `covenant/*.py` | Depends only on `mcp`, `typer`, `rich`. `diff.py` is pure (no I/O). |
| 1 proxy + quarantine | `covenant/proxy/` | `fastapi`/`httpx`/`uvicorn` are the `[proxy]` extra, lazily imported in `cli.py`. |
| 2 store | `covenant/store/` | `asyncpg` is the `[store]` extra. Store writes are best-effort: log and swallow, never fail the request path. |
| 3 probes + judge | `covenant/fingerprint.py`, `covenant/judge/` | Probes *execute* tools at snapshot/check time (list read-only tools only). `anthropic`/`google-genai` are the `[judge]` extra, imported on use; the model-name prefix picks the provider. |
| 4 observability | `covenant/proxy/metrics.py`, `deploy/` | `prometheus-client` rides the `[proxy]` extra. One `CollectorRegistry` per app, never the global registry (tests create many apps). Metric writes are in-process and non-throwing, never on the store path. Tool labels are clamped to baseline names (cardinality guard). |
| 5 k8s operator | `covenant/operator/`, `deploy/helm/` | `kopf`/`kubernetes` are the `[operator]` extra. `reconcile.py` is pure (no kopf/k8s imports — tests run cluster-free); `handlers.py` is glue only. A failed check is `status.result: error`, never a crash-loop. |

Design specs (rationale, rule tables, named decisions) live in `docs/specs/` — read the relevant spec before changing classifier or proxy behavior.

## Invariants — do not break

- **Severity classification follows the direction principle** (input-loud/output-silent). Before touching `covenant/diff.py` or arguing a tier, use the `covenant-severity` skill in `.claude/skills/`.
- `covenant.lock.json` is deterministic: sorted keys, no timestamp. Re-snapshotting an unchanged server must be byte-identical.
- `schema_hash` covers schemas only, never `description` (a typo fix must not read as an identity change).
- Drift detection is Covenant-owned (`POST /covenant/refresh` re-lists the upstream itself). Never make enforcement depend on the client's `tools/list` timing — the SDK can list *after* the call it should have protected.
- Judge verdicts are advisory: DEGRADED, never BREAKING — a probabilistic detector must not trigger quarantine (Layer 3 spec).
- Value pins (`expect` on a probe) are deterministic and exact: a mismatch is BREAKING, non-configurable. No tolerance, no regex, no auto-pinning.
- CLI errors are typed `CovenantError` → one clean line, exit 2. Never a stack trace, never swallowed.
- Exit codes are load-bearing (CI contract): 0 clean, 1 breaking (or degraded under `--strict`), 2 config/connection error.
