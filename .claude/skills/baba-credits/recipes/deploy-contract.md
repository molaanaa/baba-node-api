# Recipe: deploy a Java smart contract on Credits

## When to use
The user asks "deploy this contract", "publish this contract on Credits",
"create a smart contract on Credits", and provides Java source. The deploying
wallet (A) must have ≥ ~0.1 CS for the deploy fee.

## Prerequisites
- `BABA_PRIVATE_KEY` available, OR the embedding wallet can sign for A.
- The Java source code, with the SCAPI import on the first line.
- `monitor_get_balance({"PublicKey": A})` returns balance ≥ ~0.1 CS.

## Critical
- **`import com.credits.scapi.v0.SmartContract;` is mandatory.** Without it the
  executor compiles silently to broken bytecode.
- **`transactionInnerId` is load-bearing.** Capture it from `smartcontract_pack`
  and pass it back **unchanged** to `smartcontract_deploy`. If a parallel tx on
  the same wallet bumps `lastTransactionId+1` between Pack and Deploy, a
  re-derived inner_id will not match the signature → `"Transaction has wrong
  signature."` (no fee consumed, but you must re-pack and re-sign).

## Example contract (BasicCounter)
```java
import com.credits.scapi.v0.SmartContract;

public class BasicCounter extends SmartContract {
    private long counter = 0;

    public BasicCounter() {}

    public void increment() {
        counter += 1;
    }

    public long getCounter() {
        return counter;
    }
}
```

## Pipeline

### Step 1 — Compile
```
smartcontract_compile({"sourceCode": "<the Java above>"})
→ {
    "byteCodeObjects": [
      {"name": "BasicCounter", "byteCode": "yv66vgAAA..."}
    ],
    "tokenStandard": 0,
    "success": true
  }
```
*Compile may take up to ~120s under load — do not timeout aggressively.*

### Step 2 — Pack (deploy)
```
smartcontract_pack({
    "PublicKey": A,
    "operation": "deploy",
    "sourceCode": "<the Java above>",
    "byteCodeObjects": [{"name": "BasicCounter", "byteCode": "yv66vgAAA..."}],
    "feeAsString": "0",
    "UserData": ""
})
→ {
    "success": true,
    "dataResponse": {
      "transactionPackagedStr": "ScPack58...",
      "transactionInnerId": 7,
      "deployedAddress": "FwdrHR...",
      "recommendedFee": 0.1
    }
  }
```
*Capture `transactionPackagedStr`, `transactionInnerId`, and `deployedAddress`.*

### Step 3 — Sign client-side
See `../signing/python-pynacl.md`:
```python
sig_b58 = sign_packaged(packaged_str_b58, private_key_b58)
```

### Step 4 — Deploy
```
smartcontract_deploy({
    "PublicKey": A,
    "sourceCode": "<the same Java>",
    "byteCodeObjects": [{"name": "BasicCounter", "byteCode": "yv66vgAAA..."}],
    "TransactionSignature": sig_b58,
    "transactionInnerId": 7,
    "feeAsString": "0",
    "UserData": ""
})
→ {
    "success": true,
    "transactionId": "174580000.1",
    "deployedAddress": "FwdrHR...",
    "actualFee": "0.1"
  }
```
*`transactionInnerId` must equal the value from step 2.*

### Step 5 — Wait + confirm
```
monitor_wait_for_block({"timeoutMs": 30000})
transaction_get_info({"transactionId": "174580000.1"})
→ { "found": true, "status": "Success" }
```

The contract is now live at `deployedAddress`. Continue with
`recipes/execute-method.md` to call its methods.

## Common errors
- `node_error` "compilation error" → missing `import com.credits.scapi.v0.SmartContract;`.
- `"Transaction has wrong signature."` → `transactionInnerId` drifted between
  Pack and Deploy, OR a different `sourceCode`/`byteCodeObjects`/`feeAsString`/
  `UserData` was sent to Deploy than to Pack. Fix: re-pack, re-sign, re-deploy.
- Compile timeout under load → retry with a higher client timeout (≥ 120s).
- `node_unavailable` (503) → retry with backoff 1s/2s/4s.

## On-chain confirmation
The deploy address is deterministic: `blake2s(sourceCode ‖ inner_id_LE6 ‖
concat(byteCode))`. The Pack response already returns it, so you can show it
to the user before submission. After Deploy, use `smartcontract_get` and
`smartcontract_methods` to verify the contract is reachable.
