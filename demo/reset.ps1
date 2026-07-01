# Restore the demo to a clean pre-drift baseline (repeatable rehearsal).
# 1) revert the live tool, 2) restart it, 3) wipe Warden state, 4) re-baseline.
(Get-Content test_mcp_server/server.py -Encoding utf8) -replace 'available_balance', 'balance_usd' |
    Set-Content test_mcp_server/server.py -Encoding utf8
docker compose restart test-mcp | Out-Null
docker compose exec -T db psql -U covenant -d covenant `
    -c "TRUNCATE tool_snapshot, call_log, drift_event, tool_status;" | Out-Null
Start-Sleep -Seconds 2
Invoke-WebRequest -UseBasicParsing -Method POST http://localhost:8080/warden/refresh | Out-Null
Write-Host "reset: baseline restored, Warden state cleared." -ForegroundColor Green
