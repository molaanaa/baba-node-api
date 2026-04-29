# `baba-credits` — Troubleshooting

If you hit something not in this table, run `monitor_get_balance` against a
known-good wallet to confirm the gateway is reachable; if that fails, check
the `BABA_GATEWAY_URL` env var and call `diag_get_node_info` to verify the
node version and uptime.

## Error → cause → fix

| Symptom | Likely cause | Fix |
|---|---|---|
| `"Transaction has wrong signature."` | `transactionInnerId` changed between Pack and Execute (a parallel tx on the same wallet bumped `lastTransactionId+1`); OR Amount/Fee/UserData/method/params differ between the two calls; OR you signed the base58 *string* instead of its decoded bytes. | Re-pack, capture the new `transactionInnerId`, re-sign the **decoded raw bytes** of `transactionPackagedStr`, and resubmit with the **same** params. No fee was consumed. |
| `"Missing Data"` | `PublicKey` or `TransactionSignature` field is empty in the Execute payload. | Check that you actually populated both fields (the Pack response is dropped between agent turns surprisingly often — re-fetch if needed). |
| `"Empty Body"` | The HTTP request body is empty / the JSON payload is malformed. | Inspect the agent's outgoing payload; ensure the input dict reaches the MCP tool (e.g. you didn't pass `None` or an empty string for the whole `input` argument). |
| `"Node Unavailable"` (HTTP 503) | The Credits node is offline or restarting. | Retry with exponential backoff (1s / 2s / 4s). If three retries fail, surface the error to the user — the network itself is down. |
| `"Failed to retrieve wallet data"` (HTTP 400) | The `PublicKey` is not a valid base58 string (typo, wrong character set, wrong length). | Stop and ask the user for the correct address. Do NOT retry. |
| `node_error` on SmartContract Deploy with executor reporting "compilation error" | The Java source forgot `import com.credits.scapi.v0.SmartContract;`. The executor compiles silently to broken bytecode. | Add the import on the very first line of the source code, recompile (`smartcontract_compile`), repack, resign, redeploy. |
| `AttributeError`, Thrift schema error, or `KeyError` deep in the gateway | You're not at HEAD of the fork — the branch ships fixes for 12 schema/runtime bugs (see `docs/FOLLOW_UP.md`). | Update the local checkout to HEAD of `claude/baba-credits-mcp`, restart the MCP server, retry the tool call. |

## General principles

- **Pre-broadcast rejections do NOT consume fee.** "Wrong signature" is
  the canonical example: the node refuses to accept the tx, no fee is
  deducted from the wallet. Safe to re-pack and re-submit immediately.
- **Do not blind-retry semantic errors.** If the node returns `node_error`
  the cause is the input, not the network — fix the input first.
- **`invalid_input` is on you.** Schema-mismatch errors are caught
  client-side before any HTTP call; they never become fees and never become
  `node_error`s. Read the validation message and fix the field.
- **Keep `transactionInnerId` flowing.** Whenever a recipe involves Pack →
  Execute, the `transactionInnerId` in the Pack response is sacred: pass it
  back unchanged. This is the single most common cause of the "wrong
  signature" error.

## When in doubt

1. `diag_get_node_info` — confirm the node version and uptime.
2. `diag_get_active_transactions_count` — is the mempool healthy or backed up?
3. `monitor_get_balance` against a known wallet — is the gateway reachable?
4. Inspect the most recent `transactionId` of the affected wallet via
   `transaction_get_info` to see what the node *thinks* happened.
