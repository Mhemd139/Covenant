# Warden — 60-second live demo (beat by beat)

Nothing is simulated. A real MCP client talks through Warden to a real local MCP
server; the drift is a real edit to a live tool. Run each command in order.

**Prep (once):** `docker compose up -d --build` then `./demo/reset.ps1`
Keep a second terminal open on the live surface: `./demo/watch.ps1` (or the
dashboard at http://localhost:8080/ once Hour 5 lands).

| # | Beat (0:00–1:00) | Command | What the viewer sees |
|---|------------------|---------|----------------------|
| 0 | "Warden guards a live MCP server." | `docker compose ps` | 3 containers up; watch panel: 3 tools **OK** (green). |
| 1 | The agent does a real task. | `./demo/agent.ps1` | `[agent] Your balance is $4,210.00` — a real call through the proxy. |
| 2 | Ship a breaking change to the live tool. | `./demo/drift.ps1` | `balance_usd -> available_balance`, container restarts. |
| 3 | Warden catches it. | `Invoke-WebRequest -Method POST http://localhost:8080/warden/refresh` | JSON: `output field 'balance_usd' (number) removed`. Watch panel flips `get_account` to **QUARANTINED** (red). |
| 4 | The agent re-runs — and fails safe. | `./demo/agent.ps1` | `[agent] ABORTED — tool quarantined by Warden ... Failing safe. ✅` |
| 5 | Show what Warden prevented. | `./demo/agent.ps1 direct` | `[agent] Your balance is $0.00  ⚠️ (that number is a LIE)` — the unguarded path silently lies. |
| 6 | Close. | — | "proxy → snapshot → drift detection → quarantine. That's Warden." |
| — | Reset for the next run. | `./demo/reset.ps1` | baseline restored, all **OK** again. |

Beat 5 is the money shot: the same agent, same protocol, one guarded by Warden and
one not. Warden turns a silent, confident lie about money into a clean, safe abort.
