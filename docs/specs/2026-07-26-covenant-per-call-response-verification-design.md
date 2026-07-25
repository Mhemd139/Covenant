# Covenant — per-call response verification at the proxy

Date: 2026-07-26 · Status: designed, not yet implemented (targets v0.2.0) ·
Depends on: Layer 0 classifier, Layer 1 proxy, Layer 3 fingerprints + value pins

## Problem

Every detector Covenant has is point-in-time: `check` runs in CI, `refresh` runs when
an operator (or the k8s operator's schedule) asks. Between two checks a server can
start lying, and every `tools/call` in that window sails through the proxy untouched.
The firewall inspects the manifests (schemas at list time) but never the cargo (the
responses agents actually consume). Post-launch feedback named the gap precisely:
verify per call, not per schedule.

## Mechanism

For each `tools/call` response the proxy already holds in memory, verify the resolved
result against a per-tool **verification reference** before forwarding it.

**Reference** (compiled once per baseline load, in priority order):

1. The tool's declared `outputSchema`, when present.
2. Else the tool's **core fingerprint**: the intersection of that tool's baselined
   probe fingerprints — fields present in *every* probe response for the tool, with
   their agreed types. Intersection, not union: a field that varies across probed
   args is not core, so legitimate variance cannot false-positive.
3. Neither → the tool is unverifiable per-call; responses forward untouched and the
   `unverified` outcome is counted. The fix is documented, not automated: add a probe.

**Result resolution** reuses the Layer 3 rule verbatim (`structuredContent`, else the
first text block parsed as JSON, else raw text). A `result.isError` response skips
verification: it is already loud.

**Violation classes** are the classifier's output-side BREAKING tiers, applied to one
live response instead of a diff — plus pins:

| Live response event | Action (enforce mode) | Why |
|---|---|---|
| Reference field missing · structural retype · `null` where the reference forbids it | **block + quarantine** | Output-silent: the agent reads absence or wrongness confidently. Deterministic evidence, direction principle applies unchanged. |
| Pinned value mismatch (call args `probe_key`-match a pinned probe) | **block + quarantine** | Pins are declared truth; exact equality, no tolerance (Layer 3 invariant). |
| Scalar↔scalar retype | record DEGRADED, forward | Same tier as `check`: tolerable for LLM consumers, loud for code. Never blocks. |
| Extra fields | forward, `ok` | Additive output is COMPATIBLE. `additionalProperties: false` in an outputSchema is deliberately **not** enforced per-call: the classifier itself treats added output fields as compatible, and the verifier must not block what `check` waves through. |
| Upstream `isError` | forward, skip | Already a loud failure. |
| No reference (unprobed tool, no outputSchema) · tool not in baseline | forward, `unverified` | No truth to hold it to; measured, not hidden. |

**Blocking** replaces the response with the existing quarantine short-circuit shape: a
clean MCP `isError` result, `"quarantined by Covenant: live response violated the
output contract (<first violation>)"`. The violating response itself is blocked — the
first lie does not get one free pass; a deterministically verified violation forwarded
"just once" is the exact failure this product exists to prevent. Subsequent calls hit
the normal quarantine gate without reaching the upstream.

**Modes**: `covenant proxy` verifies and enforces by default. `--observe` detects,
records, and counts but never blocks and never quarantines — the WAF
monitor-vs-prevention pattern, for rollout against an unfamiliar upstream. Two modes,
no finer knobs.

## Quarantine: two buckets (required change)

`Quarantine.sync()` today replaces the whole set from a schema pass — and an in-band
`tools/list` runs that sync on every client connect. A response-caught liar whose
*schema* is clean would be released seconds after being caught. Therefore:

- **schema bucket** — owned by `detect()`; `sync()` replaces it, exactly as today.
  Store restore at startup (`load_quarantine`) goes through `sync()`, so it also
  feeds only this bucket.
- **response bucket** — owned by the verifier; untouched by `sync()`. Deliberately
  **not persisted**: a proxy restart behaves like a refresh, and if the server still
  lies the next live call re-quarantines it. No new store API.
- `is_quarantined` = union of both. `/covenant/status` shows each entry's source.
- `POST /covenant/refresh` clears the response bucket via an explicit
  `clear_responses()` (never via `sync()`): refresh is the operator's re-check
  button. If the server still lies, the next live call re-quarantines it —
  quarantine-on-evidence, clear-on-request, re-arm-on-recurrence. No manual unlock API.

## SSE interception (the transport that actually matters)

Streamable-HTTP servers (FastMCP included) answer `POST tools/call` over SSE, and the
Layer 1 passthrough is deliberately unbuffered — so without SSE handling this feature
verifies almost nothing in practice. Locked design:

- Only **POST** responses whose request method is `tools/call` are frame-parsed. The
  long-lived GET listen stream is never buffered, never parsed — passthrough as today.
- Frames are parsed incrementally and forwarded immediately, except the frame whose
  JSON-RPC `id` matches the request: that one is verified (in-process, sub-millisecond)
  and then forwarded — or replaced by an error frame of the same event shape. Progress
  notifications keep streaming in real time; added latency is one frame's hold.
- Per-frame buffer cap: **1 MiB** (`_VERIFY_MAX_BYTES`, module constant, tunable). Over
  the cap, the remainder of the stream forwards unverified and `skipped_large` is
  counted — a bounded verifier, never an unbounded buffer. The same cap applies to
  plain-JSON bodies: the cap bounds *verification* cost, not proxy buffering — the
  JSON path already reads whole bodies today (pre-existing, unchanged); a body over
  the cap forwards unverified and counts `skipped_large`.
- A stream that closes without the matching response frame (cancel, disconnect,
  empty stream) counts `unverified` and never quarantines — no evidence, measured
  not hidden.

## Failure policy and cost

- A verifier *exception* (our bug, unparseable frame, anything unexpected) logs and
  forwards the original bytes, outcome `error`. The firewall never drops traffic
  because its own inspection broke. Contract violations are not exceptions.
- Verification is pure in-process work on already-buffered bytes (the proxy already
  forces `accept-encoding: identity`): no I/O, no new dependencies, no LLM. Budget:
  p50 < 1 ms for bodies ≤ 64 KiB (flagged tunable, enforced by the size cap above).
- Store writes stay best-effort (`record_drift`, `record_call` with `blocked=True`);
  metrics gain `covenant_response_verifications_total{tool, outcome}` with outcomes
  `ok | violation | degraded | unverified | skipped_large | error`, tool label clamped
  to baseline names as everywhere else.

## Where the code lives

The verifier is a pure function set in `covenant/verify.py` (Layer 0 dependency rules:
no I/O, no proxy imports — the TDD anchor). The proxy calls it from the existing JSON
hook point and the new SSE frame parser. One new CLI flag (`--observe`). No config
file changes, no new extras.

## Demo lever

Start the proxy against the example server, then restart the upstream with
`COVENANT_BEHAVIOR_DRIFT=1` (or `COVENANT_SEMANTIC_DRIFT=1` with the committed pin).
The very next `tools/call` through the proxy is blocked and the tool quarantined — no
`refresh`, no `tools/list`, no CI run. That is the window this feature closes.

## Out of scope

Judge in the request path (probabilistic + latency: advisory tools never block
traffic); response repair or rewriting (block or forward, nothing in between);
auto-generated pins from live traffic (a pin the user didn't type is a pin they won't
trust); sampling rates or per-tool verification config; GET-stream verification;
non-HTTP transports at the proxy.
