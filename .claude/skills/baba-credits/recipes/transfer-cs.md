# Recipe: send CS from wallet A to wallet B

## When to use
The user asks "send N CS to <address>", "transfer CS", "pay <wallet>",
and you (the agent) have access to A's private key (or to a wallet keystore
that can sign on A's behalf).

## Prerequisites
- `BABA_PRIVATE_KEY` available, OR the embedding wallet can sign for A.
- `monitor_get_balance({"PublicKey": A})` returns balance ≥ N + estimated fee.

## Pipeline

### Step 1 — Estimate the fee
```
monitor_get_estimated_fee({"transactionSize": 9})
→ { "fee": 0.00874, "success": true }
```

### Step 2 — Verify balance
```
monitor_get_balance({"PublicKey": A})
→ { "balance": "10.0", "success": true }
```
If balance < N + fee: ABORT, tell the user.

### Step 3 — Pack the transaction
```
transaction_pack({
    "PublicKey": A,
    "ReceiverPublicKey": B,
    "amountAsString": "0.001",
    "feeAsString": "0",
    "UserData": ""
})
→ { "dataResponse": {
        "transactionPackagedStr": "<base58>",
        "recommendedFee": 0.00874
    }, "success": true }
```
*Capture the `transactionPackagedStr` for step 4.*

### Step 4 — Sign client-side
See `../signing/python-pynacl.md`:
```python
sig_b58 = sign_packaged(packaged_str_b58, private_key_b58)
```

### Step 5 — Submit
```
transaction_execute({
    "PublicKey": A,
    "ReceiverPublicKey": B,
    "amountAsString": "0.001",
    "feeAsString": "0",
    "UserData": "",
    "TransactionSignature": sig_b58
})
→ { "success": true, "transactionId": "174575023.1", "actualFee": "0.00874" }
```

### Step 6 — Confirm (optional)
```
monitor_wait_for_block({"timeoutMs": 30000})
transaction_get_info({"transactionId": "174575023.1"})
→ { "found": true, "status": "Success" }
```

## Common errors
- `"Missing Data"` — `PublicKey` or `TransactionSignature` is empty.
- `"Transaction has wrong signature."` — same `Amount`/`Fee`/`UserData` MUST
  be passed both to Pack and to Execute. If they differ, the inner_id derivation
  changes and the signature no longer matches.
- `node_unavailable` (503) — retry with backoff 1s/2s/4s.

## On-chain confirmation
A transaction is final after ~3 seconds (one pool seal). For UI feedback you
can either long-poll `monitor_wait_for_block` or short-poll `transaction_get_info`
every 2 seconds for up to 30 seconds.
