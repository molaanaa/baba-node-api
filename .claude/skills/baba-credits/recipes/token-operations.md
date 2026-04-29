# Recipe: Credits token operations

## When to use
The user asks to inspect or transfer Credits tokens — "what tokens does
wallet X hold?", "who are the top holders of token T?", "send 5 TST to
wallet B".

## Important
**Credits tokens are smart contracts**, not native CS. Reading is exposed as
a dedicated `tokens_*` category, but **transferring a token does NOT use
`transaction_pack`**. To send a token you call the token contract's
`transfer` method via `smartcontract_pack(operation="execute") →
smartcontract_execute`. See "Transferring a token" below.

## Prerequisites
- Token contract address T (base58).
- For transfers: caller wallet A's `BABA_PRIVATE_KEY` (or wallet keystore),
  and a CS balance ≥ ~0.05 CS for the execution fee.

## Pipeline

### Step 1 — Lookup token metadata
```
tokens_info({"token": T})
→ {
    "name": "TestTok",
    "code": "TST",
    "decimals": 18,
    "totalSupply": "1000000",
    "owner": "OwnerB58",
    "success": true
  }
```

### Step 2 — Multi-token wallet balance
```
tokens_balances_get({"PublicKey": W, "offset": 0, "limit": 50})
→ {
    "balances": [
      {"token": "TokB58", "code": "TST", "balance": "10.0"}
    ],
    "success": true
  }
```
*Paginate by bumping `offset`. `limit` ≤ 500.*

### Step 3 — History of a specific token
```
tokens_transfers_get({"token": T, "offset": 0, "limit": 10})
→ { "transfers": [ ... ], "success": true }
```

### Step 4 — Top holders by balance
```
tokens_holders_get({"token": T, "offset": 0, "limit": 10, "order": 0, "desc": true})
→ { "holders": [ ... ], "success": true }
```
- `order: 0` → sort by balance.
- `order: 1` → sort by transfersCount (most active addresses).
- `desc: true` → descending (default).

### Step 5 — All on-chain interactions with the token contract
```
tokens_transactions_get({"token": T, "offset": 0, "limit": 10})
→ { "transactions": [ ... ], "success": true }
```
Useful for auditing mints, burns, or admin calls (anything beyond plain
transfers).

## Transferring a token

To send tokens you must call the token contract's `transfer` method. There is
no native `tokens_transfer` tool — Credits tokens are smart contracts and
follow the standard execute pipeline:

### Step 1 — Discover the method signature
```
smartcontract_methods({"address": T})
→ {
    "methods": [
      {"name": "transfer", "args": ["string", "string"], "returnType": "boolean"},
      ...
    ],
    "success": true
  }
```
The exact `args` depend on the token standard implementation; typically
`(receiver: string, amount: string)`.

### Step 2 — Pack(execute)
```
smartcontract_pack({
    "PublicKey": A,
    "operation": "execute",
    "ReceiverPublicKey": T,
    "method": "transfer",
    "params": [
      {"K_STRING": B},
      {"K_STRING": "5.0"}
    ],
    "feeAsString": "0",
    "UserData": ""
})
→ { "dataResponse": {
        "transactionPackagedStr": "ScPack58...",
        "transactionInnerId": 9,
        "recommendedFee": 0.05
    }, "success": true }
```

### Step 3 — Sign + Execute
See `../signing/python-pynacl.md`, then:
```
smartcontract_execute({
    "PublicKey": A,
    "ReceiverPublicKey": T,
    "method": "transfer",
    "params": [
      {"K_STRING": B},
      {"K_STRING": "5.0"}
    ],
    "TransactionSignature": sig_b58,
    "transactionInnerId": 9,
    "feeAsString": "0",
    "UserData": ""
})
→ { "success": true, "transactionId": "174580020.1", "actualFee": "0.05" }
```
*`transactionInnerId` MUST equal the value from Pack; `params` MUST be
identical too.*

See `recipes/execute-method.md` for full details on the Pack/sign/Execute
flow and the Variant params format.

## Common errors
- `"Transaction has wrong signature."` (on token transfer) → drift in
  `params`, `method`, `feeAsString`, `UserData`, or `transactionInnerId`
  between Pack and Execute. Re-pack, re-sign, re-execute.
- Token method does not exist → call `smartcontract_methods({"address": T})`
  first to confirm the contract implements `transfer` (some custom tokens use
  different names).
- Insufficient token balance → the contract method itself will fail and
  `transaction_result` will report `status != "Success"`. Pre-flight with
  `tokens_balances_get`.

## On-chain confirmation
- For reads (steps 1-5): no confirmation needed — the response reflects the
  most recent sealed block.
- For transfers: use `monitor_wait_for_smart_transaction({"address": T})` or
  `transaction_get_info({"transactionId": "..."})`, then read
  `tokens_balances_get` for both sender and receiver to confirm balances
  updated.
