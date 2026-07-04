# Covenant — Layer 1: Proxy + Quarantine (design)

**Date:** 2026-07-01
**Status:** Proposed — awaiting review
**Author:** Aurelius
**Builds on:** Layer 0 (contract core) — reuses `diff.py` and `contract.py` unchanged.

## The point of this layer

Layer 0 *reports* drift (a CLI you run). Layer 1 *acts* on it: a live gateway that
sits between an agent and a real MCP server, forwards calls transparently, and the
moment a tool's contract breaks against the committed baseline, **quarantines that
tool** — a call to it returns a clean "tool unavailable" instead of being forwarded
to return a silently-wrong result. This is the memorable beat: *mutate a tool live
→ a running agent fails safe instead of hallucinating.*

## Scope discipline

- **In:** a transparent MCP reverse-proxy (streamable-HTTP), in-memory quarantine
  state, Covenant-owned drift detection reusing Layer 0, a `covenant proxy` command,
  an HTTP mode for the example server, and a runnable end-to-end demo.
- **Out (later layers):** persistence of quarantine/calls (Layer 2 = Postgres),
  behavioral/probe drift (Layer 3), metrics/dashboard (Layer 4), K8s (Layer 5).
  Quarantine state is a plain in-memory dict — deliberately, not a shortcut to hide.

## Dependencies

Layer 1 needs a web stack the core linter does not. Keep the core tiny by putting
these behind an optional extra:

```toml
[project.optional-dependencies]
proxy = ["fastapi>=0.115", "uvicorn>=0.30", "httpx>=0.27"]
```

`covenant proxy` imports them lazily and prints a clean "install covenant-mcp[proxy]"
error if missing — the `snapshot`/`check` commands never require them.

## Architecture

```
   agent (MCP client)
        │  JSON-RPC over streamable-HTTP
        ▼
   ┌──────────────────────┐   reuse Layer 0: contract.read_baseline + diff.diff_tools
   │  COVENANT PROXY      │ ── detect breaking drift ──► Quarantine (in-memory)
   │  FastAPI / httpx     │ ◄── POST /covenant/refresh   GET /covenant/status
   └──────────┬───────────┘
        │  transparent forward (byte-for-byte, SSE passthrough)
        ▼
   real MCP server (the tools)
```

Two responsibilities, cleanly split:

1. **Transparent proxy** (`covenant/proxy/server.py`): forward every JSON-RPC
   exchange to the upstream unchanged (drop hop-by-hop headers, pass SSE through
   without buffering). It observes in-band: on a `tools/list` response it runs
   detection; on a `tools/call` it enforces quarantine *before* forwarding.
2. **Covenant-owned detection** (`POST /covenant/refresh`): the proxy connects to
   the upstream *itself*, lists tools, and detects — because the client's
   `tools/list` can arrive after the call it was meant to guard (the SDK auto-lists
   post-call). Detection must not depend on client behavior. (Same lesson the old
   Warden build learned; carried forward.)

## Detection & quarantine (pure, TDD-first)

- **Baseline source:** `covenant.lock.json` (Layer 0's committed baseline), loaded
  via `contract.read_baseline`. The proxy enforces *your committed contract* — a
  strong, honest story. If no baseline exists, the first `tools/list` seen becomes
  the baseline (snapshot-on-first-sight).
- **`detect(baseline_tools, live_tools) -> dict[str, str]`** (new,
  `covenant/proxy/detect.py`): calls `diff.diff_tools`, keeps changes with
  `tier == "breaking"`, returns `{tool_name: plain-english reason}`. Pure — reuses
  the whole Layer 0 classifier, adds no new drift logic.
- **`Quarantine`** (`covenant/proxy/quarantine.py`): a thin in-memory store —
  `mark(tool, reason)`, `is_quarantined(tool) -> bool`, `reason(tool)`,
  `clear(tool)`, `all() -> dict`. No I/O. Fully unit-tested.
- **Enforcement:** a `tools/call` whose `name` is quarantined is short-circuited
  with a valid MCP error result (`{"result": {"content": [...], "isError": true}}`)
  and **never forwarded**. Degraded/compatible changes do not quarantine (they are
  observable via `/covenant/status`), matching the Layer 0 tiers.

## The `covenant proxy` command

```
covenant proxy --upstream http://localhost:8000/mcp [--baseline covenant.lock.json] [--port 9000]
```

Loads the baseline, builds the FastAPI app with a fresh `Quarantine`, and serves it
with uvicorn. Agents point at `http://localhost:9000/mcp` instead of the real server.

## Example server: add an HTTP mode

`examples/mcp_server.py` currently runs stdio (for Layer 0). Add a streamable-HTTP
mode (env `COVENANT_HTTP=1`, `PORT` default 8000) using the same tools and the same
`COVENANT_DRIFT` lever, so the proxy has a real upstream to guard. Stdio stays the
default so Layer 0 is untouched.

## The demo (nothing simulated)

```
1. start example server (HTTP, clean)         COVENANT_HTTP=1 python examples/mcp_server.py
2. start the proxy in front of it             covenant proxy --upstream http://localhost:8000/mcp
3. agent calls get_account THROUGH the proxy  → returns the balance, works
4. flip the lever + restart the server        COVENANT_DRIFT=1 ... (balance_usd -> available_balance)
5. refresh                                     curl -X POST localhost:9000/covenant/refresh
                                               → BREAKING: output field 'balance_usd' removed → QUARANTINED
6. SAME agent calls get_account again          → "tool unavailable — quarantined (contract drift)" ✅ fails safe
7. agent calls the server DIRECTLY (no proxy)  → silently returns the wrong shape ⚠️
```

Step 7 is the contrast that makes the point: same agent, one guarded, one not.

## Testing (TDD)

1. **`test_quarantine.py`** — pure store: mark/clear/is_quarantined/reason/all.
2. **`test_detect.py`** — `detect()` returns exactly the breaking tools with reasons;
   degraded/compatible do not quarantine; drives a few rows off the Layer 0 table.
3. **`test_proxy.py`** — FastAPI `TestClient` with a **mocked upstream** (httpx
   transport stub): a `tools/call` to a quarantined tool is short-circuited with
   `isError` and never reaches upstream; a healthy `tools/call` is forwarded and
   returned unchanged; a `tools/list` response triggers detection.
4. **End-to-end demo** — a script (`examples/demo_layer1.md` / `.ps1`) running both
   real servers. Automated e2e (two live sockets) is heavier and flakier; if it
   proves stable in-session I add it, otherwise the scripted demo is the honest
   coverage line and I say so rather than pretend.

## What this deliberately does NOT do

- No persistence — restart the proxy and quarantine resets (Layer 2 fixes this).
- No auto-unquarantine — once broken, a tool stays quarantined until a refresh finds
  the contract restored (re-baseline or fix the server). Simple and predictable.
- No behavioral drift — only the declared schema, exactly as Layer 0 defines it.
```
