# Build log — review-ready elevation (2026-07-03)

A record of this session's work, requested explicitly: continue the previous session's build, fix the GitHub state, and make the repo presentable to external reviewers (Codex QA, CodeRabbit).

## What the previous session actually left behind

The previous session ran with the wrong working directory, but its real output landed here and it is good: the repo was rebuilt from the demo-first "Warden" proxy into **`covenant-mcp`**, a proper package with three shipped layers (contract linter, transparent proxy + quarantine, optional Postgres store), 89 tests, and three design specs under `docs/superpowers/specs/`.

What it left broken:

1. **GitHub was stale.** `origin/main` still showed the old Warden project — the entire Covenant rebuild (3 commits) was never pushed.
2. **README described a deleted product.** `warden/`, `demo/*.ps1`, a dashboard, a screenshot — none of it exists in the tree.
3. **No LICENSE file** despite `pyproject.toml` declaring MIT; **no CI**.

## What this session verified before changing anything

- `pytest`: 86 passed, 3 skipped (Postgres tests skip without `COVENANT_TEST_DB`).
- `ruff check .` and `mypy covenant` (strict): clean.
- The demo flow works exactly as designed: `covenant check` exits 0 with the honest "no *schema* drift" caveat; `COVENANT_DRIFT=1 covenant check` catches `balance_usd` removed as BREAKING and exits 1.
- Gotcha found while verifying: the stdio launch command spawns `python` from PATH, so the venv must be active or introspection dies with `ModuleNotFoundError: mcp`. Recorded in `CLAUDE.md`.

## Changes in this branch

| Change | Why |
|---|---|
| `README.md` rewritten | Every command and output block in it was run and verified in this session. Covers linter, severity model, CI usage, proxy, store, layer roadmap. |
| `LICENSE` (MIT) | pyproject declared MIT with no license file — instant reviewer flag. |
| `.github/workflows/ci.yml` | ruff + strict mypy + pytest on 3.11/3.12/3.13 with a real Postgres service (so the 3 skipped store tests run in CI), plus a **dogfood job**: Covenant lints its own example server, then injects the breaking change and asserts exit 1. The product demos itself on every push. |
| `CLAUDE.md` (project) | Commands, layer boundaries, and the project's invariants (deterministic lock file, schema-only hash, proxy-owned detection, load-bearing exit codes) so future sessions don't re-derive or violate them. |
| `.claude/skills/covenant-severity/` | See below. |
| `docs/BUILD_LOG.md` | This file. |

## The skill, built test-first

The one piece of this project a future agent will reliably get wrong is the severity model, because it **inverts REST/OpenAPI intuition** (input changes are never BREAKING; output nullability-gain is). Per the skill-writing discipline (RED → GREEN):

- **RED:** a fresh subagent was quizzed on 4 classifications with no skill loaded. It scored **1/4** — called the new required input BREAKING (pinned-client intuition), called output nullability-gain DEGRADED, called the scalar retype BREAKING.
- **GREEN:** wrote `.claude/skills/covenant-severity/SKILL.md` countering those exact errors (consumer model, direction principle, rule table, red-flags list), then re-ran the same quiz with the skill loaded and verified 4/4.

## GitHub workflow

Direct push to `main` is blocked by policy (correctly). Everything — the previous session's 3 rebuild commits plus this branch's commits — ships in one PR from `feat/review-ready`, so CodeRabbit and Codex QA can review the entire Covenant rebuild in a single diff. Merging it fast-forwards `origin/main` to reality.

## CodeRabbit review round

CodeRabbit auto-reviewed PR #1 and raised 9 inline findings. Each was verified against the code before acting (CodeRabbit's own guidance: "fix only still-valid issues"). Eight were real and fixed; one was skipped with a reason.

| # | Finding | Verdict |
|---|---|---|
| Classifier | A union gaining a structural member (`number` → `[number, object]`) on an output field was classified as a degraded `union_widened` instead of a breaking `type_changed_structural` — a genuine silent-break gap in the core value prop | **Fixed** + regression test; the structural check now runs before the widen/narrow branches |
| Store parity | `InMemoryStore.sync_quarantine` wiped all statuses; `PostgresStore` preserves non-quarantined ones — different behavior per backend | **Fixed** to match Postgres |
| Latency | `_safe()` store writes and `/covenant/refresh` upstream re-list had no timeout; a hung dependency could stall the request path | **Fixed** — bounded both; refresh returns 502 on upstream failure |
| CLI contract | `proxy`'s dependency-missing paths bypassed the typed-error handler; `server`/`database_url` typed `str` but default to `None` | **Fixed** — route through `CovenantError`, annotate `str | None` |
| Baseline | lock file hardcoded a Windows `.venv` path instead of the configured command | **Fixed** — re-snapshotted via `covenant.toml`; diff is byte-identical except the server line |
| README | "every call and drift event is persisted" overstated a best-effort store | **Fixed** — softened |
| Spec map | Layer 0 spec's module map "missing" `proxy` | **Skipped** — proxy is Layer 1 scope, documented in the Layer 1 spec |

After the fixes: `pytest` 87 passed / 3 skipped, `ruff` + `mypy --strict` clean, drift demo still 0 (clean) / 1 (breaking). This is the loop working as designed — an external reviewer found a real classifier bug, and the contract-check dogfood job plus the rule-table tests caught the fix landing correctly.

## Layer 3 — behavioral probes + semantic judge (same day, second branch)

`feat/layer3-behavioral-probes`. A clean schema check can't see a lying server, and most real MCP tools declare no `outputSchema` at all. Layer 3 adds `[[probes]]` (safe example calls in `covenant.toml`): `snapshot` fingerprints each response's *type shape* into the lock, `check` re-runs the probes and classifies drift **with the unchanged Layer 0 classifier** (responses are output-side by definition), rendered at location `behavior`. `covenant check --judge` (optional `[judge]` extra) additionally sends baseline sample + live response to an LLM for semantic drift (dollars→cents) — verdicts are advisory DEGRADED, never BREAKING, so a probabilistic detector cannot cause a quarantine outage.

Verified end-to-end: 112 tests (22 new), ruff + strict mypy clean, lock still byte-deterministic after re-snapshot, `COVENANT_BEHAVIOR_DRIFT=1` (schema untouched, body renames a field) exits 1 via the probe path, and the classic `COVENANT_DRIFT=1` is now caught twice — declared schema and actual body. CI dogfood gained the behavioral lever. Design: `docs/superpowers/specs/2026-07-03-covenant-layer3-behavioral-probes-design.md`.
