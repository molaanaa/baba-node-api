# API payload examples

JSON request/response samples for every endpoint exposed by `gateway.py` +
`routes/*`. Organised by section (mirrors `routes/`).

**File format**

Each `*.json` file is a single object with these keys:

```json
{
  "endpoint": "/api/<path>",
  "method": "POST",
  "description": "what the call does",
  "request": { ...example body... },
  "response_success": { ...example 200 body... },
  "response_error": { ...example 4xx/5xx body... },
  "notes": "optional gotchas, parameter aliases, on-chain side-effects"
}
```

The shapes are stable across both the bare `/<path>` and `/api/<path>`
mounts; pick whichever the host wants to expose to the public internet
behind Nginx.

**Index**

| Section | Files |
|---|---|
| `monitor/` | `GetWalletInfo`, `GetBalance`, `GetTransactionsByWallet`, `GetEstimatedFee` |
| `transaction/` | `Pack`, `Execute`, `GetTransactionInfo`, `Result` |
| `smartcontract/` | `Compile`, `Get`, `Methods`, `State`, `ListByWallet`, `Pack`, `Deploy`, `Execute` |
| `tokens/` | `BalancesGet`, `TransfersGet`, `Info`, `HoldersGet`, `TransactionsGet` |
| `monitor_wait/` | `WaitForBlock`, `WaitForSmartTransaction` |
| `diag/` | `GetActiveNodes`, `GetActiveTransactionsCount`, `GetNodeInfo`, `GetSupply` |
| `userfields/` | `Encode`, `Decode` |

**Conventions**

- Addresses, signatures, hashes: always **base58** on the JSON layer.
- Bytecode (smart contracts): **base64** (matches `SmartContractCompile`'s
  output and what the node consumes back).
- Amounts: strings (`"0.001"`) to avoid IEEE-754 truncation; the gateway
  parses them via `Decimal`.
- Fees: `feeAsString` is the **maximum** fee the client authorises; the
  node-side actual fee comes back in the response.
- `transactionId` format is `"<poolSeq>.<index1>"` (1-based index).
- Long-poll endpoints: `timeoutMs` clamped to `WAIT_MAX_TIMEOUT_MS`
  (default 120000ms).

**Try the examples**

```bash
curl -X POST http://localhost:5000/api/Monitor/GetBalance \
  -H "Content-Type: application/json" \
  -d "$(jq -c .request payloads/monitor/GetBalance.json)"
```
