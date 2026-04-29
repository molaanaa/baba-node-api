# Recipe: read-only inspection of a Credits wallet

## When to use
The user asks "what's in wallet X?", "show me wallet X", "what has wallet X
been doing?", "give me a snapshot of wallet X". You only need to **read**
on-chain state — no signing, no fee, no key required.

## Prerequisites
- A base58 wallet `PublicKey` (call it W).
- The MCP server is connected.

## Pipeline

### Step 1 — Wallet info (balance + last tx + delegations)
```
monitor_get_wallet_info({"PublicKey": W})
→ {
    "balance": "100.0",
    "lastTransaction": 42,
    "delegated": {
      "incoming": 0,
      "outgoing": 0,
      "donors": [],
      "recipients": []
    },
    "success": true
  }
```

### Step 2 — Recent activity (paginated)
```
monitor_get_transactions_by_wallet({"PublicKey": W, "offset": 0, "limit": 10})
→ {
    "transactions": [
      {"id": "174575023.1", "fromAccount": "W", "toAccount": "B",
       "value": "0.001", "fee": "0.00874", "currency": "CS",
       "time": "2026-04-27T12:00:00.000Z", "status": "Success"},
      ...
    ],
    "success": true
  }
```
*Increase `offset` (`offset += limit`) for older history; `limit` up to 500.*

### Step 3 — Token holdings (paginated)
```
tokens_balances_get({"PublicKey": W, "offset": 0, "limit": 10})
→ {
    "balances": [
      {"token": "TokB58", "code": "TST", "balance": "10.0"}
    ],
    "success": true
  }
```

## Synthesizing the output for the user

Keep the summary tight (~5 lines) so the user gets a snapshot at a glance.

Example output:
```
Wallet abc...xyz
- CS balance: 100.0 (last tx: 42)
- Delegations: 0 in / 0 out
- Recent activity: 10 transactions, latest 174575023.1 (Success, 0.001 CS to B)
- Tokens: 1 (10.0 TST)
```

If the wallet is "empty" (zero balance, zero history, no tokens), say so
explicitly so the user knows the address is valid but unused.

## Common errors
- `"Failed to retrieve wallet data"` (HTTP 400) → `PublicKey` is not a valid
  base58 string. Stop and ask the user for the correct address.
- `not_found` → wallet has never appeared on-chain (no transactions). This is
  not a hard error; report "no on-chain history".
- `node_unavailable` (503) → retry the whole pipeline with backoff 1s/2s/4s.

## On-chain confirmation
This recipe is purely read-only — no on-chain confirmation step needed. If
the user wants live updates, wrap the pipeline in a `monitor_wait_for_block`
loop and re-run on each new pool seal.
