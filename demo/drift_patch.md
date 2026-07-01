# The drift patch (the exact breaking change)

`./demo/drift.ps1` applies this to the live tool in `test_mcp_server/server.py`:

```diff
 class AccountInfo(BaseModel):
     account_id: str
     holder: str
-    balance_usd: float
+    available_balance: float
     currency: str

 @mcp.tool()
 def get_account(account_id: str) -> AccountInfo:
     ...
     return AccountInfo(
         account_id=account_id,
         holder=holder,
-        balance_usd=balance,
+        available_balance=balance,
         currency=currency,
     )
```

Why it's breaking: `balance_usd` is a field the downstream agent **reads and reports**.
Renaming it removes `balance_usd` from the tool's declared `outputSchema`. A consumer
that does `data.get("balance_usd")` now gets nothing and silently reports the wrong
number. Warden classifies the removal as BREAKING and quarantines the tool before the
lie can happen.

`./demo/reset.ps1` reverses the rename to restore the baseline.
