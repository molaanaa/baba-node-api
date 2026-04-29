---
name: baba-credits
description: |
  Use when the user wants to interact with the Credits blockchain via the
  baba-credits MCP server — sending CS transfers, deploying/calling Java
  smart contracts, querying balances, transactions, tokens, attaching
  userFields metadata (ArtVerse-style), or running node diagnostics.
  Triggers when the user mentions: Credits, CS coin, $CS, baba-credits,
  Credits wallet, BABA Wallet, smart contract on Credits, ArtVerse mint.
---

# baba-credits

## TL;DR

You are talking to a Python MCP server (`baba-credits`) that wraps the BABA Wallet
HTTP gateway, which in turn talks Thrift to a Credits node. The server is
**non-custodial**: it never holds private keys. All write operations require the
client (you, or the wallet you're embedded in) to produce an ed25519 signature
and submit it to the server.

The canonical pipeline for any write is:

    1. *_pack         → returns base58 transactionPackagedStr (and innerId)
    2. (client-side)  → ed25519 sign of the raw bytes of that base58 blob
    3. *_execute      → submit signed payload + same params + same innerId
    4. (optional)     → monitor_wait_for_block / transaction_get_info

For read-only inspection just call the corresponding `*_get_*`, `*_info`,
`*_state`, or `diag_*` tool directly.

## Decision tree — which tool do I use?

- "How much CS does wallet X hold?" → `monitor_get_balance`
- "What did wallet X do recently?" → `monitor_get_transactions_by_wallet`
- "What is transaction 174575023.1?" → `transaction_get_info`
- "Did my smart-contract call succeed?" → `transaction_result`
- "Send N CS from A to B" → recipe `transfer-cs.md`
- "Deploy this Java contract" → recipe `deploy-contract.md`
- "Call method `x` on contract C" → recipe `execute-method.md`
- "Mint an ArtVerse asset" → recipe `attach-metadata.md` + `transfer-cs.md`
- "Show me details of the network" → `diag_*`
- "Wait until the next block" → `monitor_wait_for_block` (long-poll)

## Critical constraints (read before writing)

These come from on-chain validation in 2026-04-27/28 and are NOT optional:

1. **Fix `transactionInnerId` between Pack and Execute.** `*_pack` derives
   inner_id from `lastTransactionId+1`. If a parallel transaction on the same
   wallet bumps that counter between your Pack and your Execute, the rebuilt
   inner_id at submit time differs and the node rejects with `"Transaction has
   wrong signature."` — pre-broadcast (no fee consumed). Fix: read
   `transactionInnerId` from the Pack response and pass it back to
   `*_deploy/_execute`.

2. **Java smart contracts MUST import the SCAPI explicitly.** The first line
   of source must include `import com.credits.scapi.v0.SmartContract;`. Without
   it the executor compiles silently to broken bytecode.

3. **Deploy address is deterministic.** It is `blake2s(source ‖ inner_id_LE6 ‖
   concat(byteCode))`. The Pack response includes `deployedAddress` so you
   don't need to recompute it client-side; but if you do, the formula above is
   the exact one used by the node.

4. **Compile is slow.** Up to ~120s under load. Do not timeout aggressively.

5. **`transaction_execute` rejected with "wrong signature" does NOT consume
   fee.** This is a safety feature of the node. It also means the agent
   should NOT retry blindly — re-pack, re-sign, re-submit instead.

## Tools — quick reference

See `tools-reference.md` for the full catalog (29 tools, 6 categories).

| Category | Count | Notable |
|---|---|---|
| `monitor_*` | 6 | balance, history, fee estimation, long-poll waits |
| `transaction_*` | 4 | get/pack/execute/result for plain CS transfers |
| `userfields_*` | 2 | encode/decode of v1 metadata blobs (ArtVerse) |
| `tokens_*` | 5 | balances, transfers, info, holders, transactions |
| `smartcontract_*` | 8 | compile, pack, deploy, execute, get, methods, state, list |
| `diag_*` | 4 | active nodes, mempool count, node info, supply |

## Recipes (full pipelines)

- `recipes/transfer-cs.md` — send CS from A to B
- `recipes/deploy-contract.md` — Java contract on-chain
- `recipes/execute-method.md` — call a method on a deployed contract
- `recipes/inspect-wallet.md` — read-only exploration
- `recipes/attach-metadata.md` — userFields v1 (ArtVerse minting)
- `recipes/token-operations.md` — token info / balances / transfers / holders

## Client-side signing

The MCP server NEVER signs. You sign client-side. See:

- `signing/python-pynacl.md` — 5 lines of Python (validated on-chain 2026-04-27)
- `signing/typescript-tweetnacl.md` — equivalent for JS/TS wallets

If you are an "agent with a key" the private key is in your env (`BABA_PRIVATE_KEY`).
If you are embedded in a smart wallet, the wallet keystore signs without exposing the key.

## Errors — what they mean and what to do

| Code | Meaning | Action |
|---|---|---|
| `invalid_input` | Schema mismatch (e.g. malformed transactionId) | Do NOT retry. Fix the input. |
| `not_found` | Tx/contract does not exist | Stop searching. |
| `node_unavailable` | Credits node offline (HTTP 503) | Retry with backoff (1s/2s/4s). |
| `node_error` | Semantic error from node (e.g. wrong signature) | Do NOT blind-retry. Re-pack, re-sign. |
| `rate_limited` | Gateway rate limit hit | Wait `Retry-After` then retry. |
| `internal` | Unexpected gateway error | Surface to the user; collect details. |

## When NOT to use this skill

- The MCP server `baba-credits` is not connected in the current session.
- The user asks for a custodial action ("create me a wallet", "store my keys").
  We do NOT generate or store private keys. Direct them to the BABA Wallet app.
- The user asks about a different blockchain (Ethereum, Solana, etc.).

## Troubleshooting

See `troubleshooting.md` for the mapping of common error messages to causes
and fixes (covers the 12 schema/runtime bugs already fixed in the codebase).
