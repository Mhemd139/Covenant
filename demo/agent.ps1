# Run the deterministic agent task. Default: through Warden (guarded).
#   ./demo/agent.ps1           # via Warden  -> safe (aborts on drift)
#   ./demo/agent.ps1 direct    # via the MCP server directly -> lies on drift
param([string]$Target = "warden")
$mcp = if ($Target -eq "direct") { "http://test-mcp:8000/mcp" } else { "http://warden:8080/mcp" }
docker compose run --rm -T -v "${PWD}:/work" -w /work -e WARDEN_MCP_URL=$mcp `
    test-mcp python demo/agent_task.py
