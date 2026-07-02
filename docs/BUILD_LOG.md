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
