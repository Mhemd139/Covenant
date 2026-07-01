# BONUS beat: trigger a recursive-delegation (A2A DoS) loop through Warden.
# Warden's depth breaker trips past the limit and quarantines `delegate`.
docker compose run --rm -T -v "${PWD}:/work" -w /work -e WARDEN_MCP_URL=http://warden:8080/mcp `
    test-mcp python demo/a2a_task.py
