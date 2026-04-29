# Recipe: call a method on a deployed Credits smart contract

## When to use
The user asks "call method `m` on contract C", "increment the counter on
contract C", "execute X on this contract". The caller wallet (A) must have
≥ ~0.05 CS available for the execution fee.

## Prerequisites
- `BABA_PRIVATE_KEY` available, OR the embedding wallet can sign for A.
- Contract address C (base58) already deployed on-chain.
- `monitor_get_balance({"PublicKey": A})` returns enough CS for the fee.

## Critical
- **`transactionInnerId` is load-bearing.** Capture it from `smartcontract_pack`
  and pass it back unchanged to `smartcontract_execute`. Same drift constraint
  as `deploy-contract.md`.
- **Pass-through invariant.** `method`, `params`, `feeAsString`, `UserData`,
  `PublicKey`, `ReceiverPublicKey` MUST be identical between Pack and Execute.

## Pipeline

### Step 1 — Discover available methods
```
smartcontract_methods({"address": C})
→ {
    "methods": [
      {"name": "getCounter", "args": [], "returnType": "long"},
      {"name": "increment", "args": [], "returnType": "void"}
    ],
    "success": true
  }
```
*Pick the method to call and assemble its `params` (Variant list — see below).*

### Step 2 — Pack (execute)
```
smartcontract_pack({
    "PublicKey": A,
    "operation": "execute",
    "ReceiverPublicKey": C,
    "method": "increment",
    "params": [],
    "feeAsString": "0",
    "UserData": ""
})
→ {
    "success": true,
    "dataResponse": {
      "transactionPackagedStr": "ScPack58...",
      "transactionInnerId": 8,
      "recommendedFee": 0.05
    }
  }
```
*Capture `transactionPackagedStr` and `transactionInnerId`.*

### Step 3 — Sign client-side
See `../signing/python-pynacl.md`:
```python
sig_b58 = sign_packaged(packaged_str_b58, private_key_b58)
```

### Step 4 — Execute
```
smartcontract_execute({
    "PublicKey": A,
    "ReceiverPublicKey": C,
    "method": "increment",
    "params": [],
    "TransactionSignature": sig_b58,
    "transactionInnerId": 8,
    "feeAsString": "0",
    "UserData": ""
})
→ {
    "success": true,
    "transactionId": "174580010.1",
    "actualFee": "0.05"
  }
```
*`transactionInnerId` must equal the value from step 2.*

### Step 5 — Get the result
```
transaction_result({"transactionId": "174580010.1"})
→ {
    "transactionId": "174580010.1",
    "found": true,
    "executionTime": 12,
    "returnValue": null,
    "success": true
  }
```
For methods with a non-void return, `returnValue` is a Variant dict (see below)
encoding the value. For state-mutating methods you typically don't need it;
read the contract state instead with `smartcontract_state`.

## Variant params format

`params` is a JSON array where each element is a `{type: value}` dict (the
Credits Variant tagged-union). The MCP server passes this list through to the
gateway unchanged. The internal helper `services/monitor.py:_variant_to_python`
reverses the mapping when decoding `returnValue`.

For the simplest case — a method with no arguments — pass `params: []`.

For arguments, the dict shape mirrors the gateway-side Variant tags. Common
shapes you might encounter:
```json
[
  {"K_INTEGER": 42},
  {"K_LONG": 1000000000},
  {"K_STRING": "hello"},
  {"K_BOOLEAN": true}
]
```
The exact tag names depend on the gateway version. If the contract method
takes complex arguments (lists, custom objects), consult the BABA Wallet
gateway docs and/or call `smartcontract_methods` to see the expected types.
For void or no-arg methods, just pass `[]` and you'll never need to worry
about Variant tags.

## Common errors
- `"Transaction has wrong signature."` → `transactionInnerId` drifted, or
  `method`/`params`/`feeAsString`/`UserData` differs between Pack and Execute.
  Fix: re-pack, re-sign, re-execute.
- `"Missing Data"` — `PublicKey`, `ReceiverPublicKey`, or `TransactionSignature`
  empty.
- Method does not exist on contract → `smartcontract_methods` first.
- `node_unavailable` (503) → retry with backoff 1s/2s/4s.

## On-chain confirmation
After `smartcontract_execute` returns successfully, the transaction is queued
in the mempool. To confirm it sealed:
- `monitor_wait_for_smart_transaction({"address": C, "timeoutMs": 30000})`, or
- `transaction_get_info({"transactionId": "..."})` and check `"status":
  "Success"`,
- and then `smartcontract_state({"address": C})` to read the new state.
