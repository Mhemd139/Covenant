# Ship a BREAKING change to the LIVE tool: rename get_account's output field
# balance_usd -> available_balance, then restart just that container.
(Get-Content test_mcp_server/server.py) -replace 'balance_usd', 'available_balance' |
    Set-Content test_mcp_server/server.py -Encoding utf8
docker compose restart test-mcp | Out-Null
# Wait for the live tool to accept connections again (any HTTP reply = up).
for ($i = 0; $i -lt 20; $i++) {
    try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/mcp -TimeoutSec 1 | Out-Null; break }
    catch { if ($_.Exception.Response) { break }; Start-Sleep -Milliseconds 400 }
}
Write-Host "drift shipped: get_account.balance_usd -> available_balance (live tool restarted)" -ForegroundColor Yellow
