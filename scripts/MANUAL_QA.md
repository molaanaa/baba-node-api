# Manual QA — `baba-credits` MCP server

This checklist is the **pre-release** smoke pass. Run it before tagging a new
version of the MCP server or merging M10 to `main`. It exercises the full
`baba-credits` stack end-to-end against a real Credits node, in a way the unit
tests in CI can't (CI never spends fee or signs anything).

## Prerequisites

- A reachable Credits node (see `env_server.md` — default `38.242.234.47:9090`).
- The BABA Wallet HTTP gateway running locally on `http://127.0.0.1:5000`
  (start it with `pm2 start ecosystem.config.js --only baba-gateway`).
- The MCP server importable from the active virtualenv (`source .venv/bin/activate`).
- A funded sender wallet (pubkey + 64-byte secret in base58) and a receiver
  pubkey. Put them in env vars:

  ```bash
  export BABA_PUBLIC_KEY=...        # sender pubkey, base58
  export BABA_PRIVATE_KEY=...       # sender secret, base58 (64 bytes)
  export BABA_RECEIVER=...          # receiver pubkey, base58
  ```

## Checklist

- [ ] **Gateway healthy.** `curl -fsS http://127.0.0.1:5000/healthz` returns 200.
- [ ] **MCP server starts (stdio).** `python -m baba_mcp.server` launches
      without traceback; Ctrl-C stops it cleanly.
- [ ] **MCP server starts (http).** `python -m baba_mcp.server --transport http`
      binds the configured port and responds to a `tools/list` request.
- [ ] **Skill loaded.** In Claude Code, `/skills` shows `baba-credits` with
      the description from `SKILL.md`.
- [ ] **On-chain smoke passes.** Run:

  ```bash
  source .venv/bin/activate
  python scripts/mcp_onchain_smoke.py
  ```

  Expected output:
  - `balance: <non-zero>`
  - `supply: {...}`
  - `pack ok, recommendedFee: <float>`
  - `execute: <txid> True`
  - `status: Success`

- [ ] **Drift test green.** `pytest tests/test_skill_drift.py -v` shows 4/4 PASSED.
- [ ] **Full unit suite green.** `pytest tests/ -q` shows `113 passed, 1 skipped`.

## What to do if the smoke fails

| Symptom | Likely cause | Fix |
|---|---|---|
| `connection refused :5000` | gateway down | `pm2 start baba-gateway` |
| `Transaction has wrong signature` | inner_id drift between Pack and Execute | re-pack, re-sign, re-submit |
| `node_unavailable` | Credits node offline | check node host / wait |
| `KeyError: BABA_PRIVATE_KEY` | env var missing | export the three required vars |
