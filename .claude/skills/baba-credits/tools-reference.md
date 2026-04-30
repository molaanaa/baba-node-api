# `baba-credits` — Tools Reference

Catalog of the 29 tools exposed by the `baba-credits` MCP server, grouped by
category in this order: `monitor_*`, `transaction_*`, `userfields_*`,
`tokens_*`, `smartcontract_*`, `diag_*`.

For each tool: REST endpoint hit on the BABA Wallet gateway, MCP annotations
(`readOnlyHint`, `destructiveHint`, `idempotentHint`), required input fields
(by alias — the gateway accepts both PascalCase aliases and snake_case names),
a sample output JSON taken from the test fixtures, and a short "When to use"
hint.

The full Pydantic input schemas live in `baba_mcp/tools/<category>.py`.

---

## monitor_*

Wallet inspection, fee estimation, and long-poll waits. Everything in this
category is read-only — safe to call freely without ever touching a private
key.

### `monitor_get_balance`
**Endpoint:** `POST /api/Monitor/GetBalance`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | wallet address |

**Output (sample):**
```json
{
  "balance": "1.234",
  "tokens": [],
  "delegatedOut": 0,
  "delegatedIn": 0,
  "success": true,
  "message": "Tokens not supported"
}
```

**When to use:** Quick CS balance check for a wallet, including delegation totals.

---

### `monitor_get_wallet_info`
**Endpoint:** `POST /api/Monitor/GetWalletInfo`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | wallet address |

**Output (sample):**
```json
{
  "balance": "100.0",
  "lastTransaction": 42,
  "delegated": {
    "incoming": 0,
    "outgoing": 0,
    "donors": [],
    "recipients": []
  },
  "success": true,
  "message": null
}
```

**When to use:** Full wallet snapshot — balance, lastTransactionId (used by
Pack to derive inner_id), and the donors/recipients lists for delegation.

---

### `monitor_get_transactions_by_wallet`
**Endpoint:** `POST /api/Monitor/GetTransactionsByWallet`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | wallet address |
| `offset` | int (≥0) | no | default 0 |
| `limit` | int (1..500) | no | default 10 |

**Output (sample):**
```json
{
  "transactions": [],
  "success": true,
  "message": null
}
```

**When to use:** Paginated transaction history for a wallet (id, sum, fee,
from/to, time, status, currency).

---

### `monitor_get_estimated_fee`
**Endpoint:** `POST /api/Monitor/GetEstimatedFee`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `transactionSize` | int (≥0) | yes | byte size of the future tx |

**Output (sample):**
```json
{
  "fee": 0.00874,
  "success": true,
  "message": ""
}
```

**When to use:** Pre-flight fee estimation. Cheaper alternative: pass
`feeAsString="0"` to `*_pack` and read `recommendedFee` from the response.

---

### `monitor_wait_for_block`
**Endpoint:** `POST /api/Monitor/WaitForBlock`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `timeoutMs` | int (0..60000) | no | default 30000 |
| `poolHash` | string (base58) | no | optional cursor (last seen block hash) |

**Output (sample):**
```json
{
  "blockHash": "PoolHashB58...",
  "changed": true,
  "success": true
}
```

**When to use:** Long-poll until a new pool is sealed; ideal after a
`*_execute` call to confirm the transaction is on-chain.

---

### `monitor_wait_for_smart_transaction`
**Endpoint:** `POST /api/Monitor/WaitForSmartTransaction`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `address` | string (base58) | yes | contract address to watch |
| `timeoutMs` | int (0..60000) | no | default 30000 |

**Output (sample):**
```json
{
  "transactionId": "12345.1",
  "found": true,
  "success": true
}
```

**When to use:** Long-poll until the next smart-contract transaction targeting
`address` is sealed.

---

## transaction_*

The classic CS transfer pipeline: get info, build canonical Pack payload, sign
client-side, submit Execute, optionally fetch the smart-contract Result.

### `transaction_get_info`
**Endpoint:** `POST /api/Transaction/GetTransactionInfo`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `transactionId` | string `<poolSeq>.<index1>` | yes | e.g. `174575023.1` |

**Output (sample):**
```json
{
  "id": "174575023.1",
  "fromAccount": "A",
  "toAccount": "B",
  "time": "2026-04-27T12:00:00.000Z",
  "value": "0.001",
  "fee": "0.00874",
  "currency": "CS",
  "innerId": 12,
  "status": "Success",
  "transactionType": 0,
  "transactionTypeDefinition": "TT_Normal",
  "blockNum": "174575023",
  "found": true,
  "userData": "",
  "signature": "Sig58...",
  "success": true,
  "message": null
}
```

**When to use:** Inspect a specific transaction by id (after a transfer to
confirm it landed, or for forensic look-ups).

---

### `transaction_pack`
**Endpoint:** `POST /api/Transaction/Pack`  **Annotations:** idempotent

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | source wallet |
| `ReceiverPublicKey` | string (base58) | yes | target wallet |
| `amountAsString` | string | no | default `"0"` |
| `feeAsString` | string | no | default `"0"` (uses recommendedFee) |
| `UserData` | string (base58) | no | default `""`; e.g. userFields v1 blob |
| `DelegateEnable` | bool | no | default false |
| `DelegateDisable` | bool | no | default false |
| `DateExpiredUtc` | string | no | default `""` |

**Output (sample):**
```json
{
  "success": true,
  "dataResponse": {
    "transactionPackagedStr": "Pack58...",
    "recommendedFee": 0.00874,
    "actualSum": 0,
    "publicKey": null,
    "smartContractResult": null
  },
  "transactionInnerId": null,
  "message": null
}
```

**When to use:** Step 1 of a CS transfer. Take `transactionPackagedStr`,
decode from base58, ed25519-sign the raw bytes, then pass the **same**
amount/fee/UserData unchanged to `transaction_execute`.

---

### `transaction_execute`
**Endpoint:** `POST /api/Transaction/Execute`  **Annotations:** destructive

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | source wallet (same as Pack) |
| `ReceiverPublicKey` | string (base58) | yes | target wallet (same as Pack) |
| `amountAsString` | string | no | MUST equal Pack's value |
| `feeAsString` | string | no | MUST equal Pack's value |
| `UserData` | string | no | MUST equal Pack's value |
| `TransactionSignature` | string (base58) | yes | ed25519 signature of decoded Pack bytes |

**Output (sample):**
```json
{
  "success": true,
  "transactionId": "174575023.1",
  "actualFee": "0.00874",
  "actualSum": "0.001",
  "transactionInnerId": 13,
  "message": null
}
```

**When to use:** Step 3 of a CS transfer. Submits the signed payload to the
node. If parameters drift between Pack and Execute the node rejects with
`"Transaction has wrong signature."` (no fee consumed).

---

### `transaction_result`
**Endpoint:** `POST /api/Transaction/Result`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `transactionId` | string `<poolSeq>.<index1>` | yes | smart-contract tx id |

**Output (sample):**
```json
{
  "transactionId": "174575023.1",
  "found": true,
  "executionTime": 12,
  "returnValue": null,
  "success": true,
  "message": null
}
```

**When to use:** Fetch the SmartExecutionResult of a smart-contract
transaction (executionTime, returnValue Variant, status).

---

## userfields_*

Pure codec for the userFields v1 blob format used to inscribe ordinals-style
on-chain metadata (digest + IPFS CID + mime + size) onto a Credits transaction.
Both tools are read-only / idempotent — they never write on-chain.

### `userfields_encode`
**Endpoint:** `POST /api/UserFields/Encode`  **Annotations:** read-only, idempotent

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `contentHashAlgo` | string | no | default `"sha-256"` |
| `contentHash` | string (hex) | yes | digest of the asset |
| `contentCid` | string | no | IPFS CID (optional but recommended) |
| `mime` | string | no | e.g. `image/png` |
| `sizeBytes` | int (≥0) | no | size of the asset in bytes |

**Output (sample):**
```json
{
  "success": true,
  "userData": "uF58...",
  "message": null
}
```

**When to use:** Build the base58 `UserData` blob to attach ordinals-style
on-chain metadata to a `transaction_pack`/`transaction_execute` call
(asset inscription).

---

### `userfields_decode`
**Endpoint:** `POST /api/UserFields/Decode`  **Annotations:** read-only, idempotent

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `userData` | string (base58) | yes | the v1 blob from a tx's `userData` |

**Output (sample):**
```json
{
  "success": true,
  "fields": {
    "contentHashAlgo": "sha-256",
    "contentHash": "0011...",
    "contentCid": "bafy...",
    "mime": "image/png",
    "sizeBytes": 1234567
  },
  "message": null
}
```

**When to use:** Decode the `userData` field of a transaction back into the
structured v1 metadata fields.

---

## tokens_*

Credits "tokens" are smart contracts implementing a standard interface.
Reading their state is exposed as a dedicated category; **transferring**
tokens still requires `smartcontract_execute` with `method="transfer"` (see
`recipes/token-operations.md`).

### `tokens_info`
**Endpoint:** `POST /api/Tokens/Info`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `token` | string (base58) | yes | token contract address |

**Output (sample):**
```json
{
  "name": "TestTok",
  "code": "TST",
  "decimals": 18,
  "totalSupply": "1000000",
  "owner": "OwnerB58",
  "success": true,
  "message": null
}
```

**When to use:** Resolve the metadata of a token contract (name, code,
decimals, totalSupply, owner).

---

### `tokens_balances_get`
**Endpoint:** `POST /api/Tokens/BalancesGet`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | wallet address |
| `offset` | int (≥0) | no | default 0 |
| `limit` | int (1..500) | no | default 10 |

**Output (sample):**
```json
{
  "balances": [
    {"token": "TokB58", "code": "TST", "balance": "10.0"}
  ],
  "success": true,
  "message": null
}
```

**When to use:** Multi-token balance for a wallet (paginated).

---

### `tokens_transfers_get`
**Endpoint:** `POST /api/Tokens/TransfersGet`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `token` | string (base58) | yes | token contract address |
| `offset` | int (≥0) | no | default 0 |
| `limit` | int (1..500) | no | default 10 |

**Output (sample):**
```json
{
  "transfers": [],
  "success": true,
  "message": null
}
```

**When to use:** Recent transfer history of a specific token.

---

### `tokens_holders_get`
**Endpoint:** `POST /api/Tokens/HoldersGet`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `token` | string (base58) | yes | token contract address |
| `offset` | int (≥0) | no | default 0 |
| `limit` | int (1..500) | no | default 10 |
| `order` | int | no | 0=balance, 1=transfersCount (default 0) |
| `desc` | bool | no | default true |

**Output (sample):**
```json
{
  "holders": [],
  "success": true,
  "message": null
}
```

**When to use:** Top holders of a token by balance (or by activity, with
`order=1`).

---

### `tokens_transactions_get`
**Endpoint:** `POST /api/Tokens/TransactionsGet`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `token` | string (base58) | yes | token contract address |
| `offset` | int (≥0) | no | default 0 |
| `limit` | int (1..500) | no | default 10 |

**Output (sample):**
```json
{
  "transactions": [],
  "success": true,
  "message": null
}
```

**When to use:** All on-chain transactions interacting with a specific token
contract (mint/burn/transfer).

---

## smartcontract_*

Eight tools covering the full lifecycle of a Java smart contract on Credits:
compile → pack(deploy) → deploy, then pack(execute) → execute, plus
get/methods/state/list for inspection. Both Deploy and Execute go through the
same `Pack → sign → submit` pattern as `transaction_*`, with the additional
`transactionInnerId` invariant.

### `smartcontract_compile`
**Endpoint:** `POST /api/SmartContract/Compile`  **Annotations:** read-only, idempotent

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `sourceCode` | string | yes | Java source — MUST include `import com.credits.scapi.v0.SmartContract;` |

**Output (sample):**
```json
{
  "byteCodeObjects": [
    {"name": "BasicCounter", "byteCode": "yv66vgAAA..."}
  ],
  "tokenStandard": 0,
  "success": true,
  "message": null
}
```

**When to use:** Step 1 of a deploy: produce the base64-encoded
`byteCodeObjects` from Java source. Slow (up to ~120s under load).

---

### `smartcontract_pack`
**Endpoint:** `POST /api/SmartContract/Pack`  **Annotations:** idempotent

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | deployer/caller |
| `operation` | string | yes | `"deploy"` or `"execute"` |
| `ReceiverPublicKey` | string (base58) | for execute | contract address |
| `sourceCode` | string | for deploy | Java source (with SCAPI import) |
| `byteCodeObjects` | list[{name,byteCode}] | for deploy | from `smartcontract_compile` |
| `method` | string | for execute | method name |
| `params` | list[Variant] | for execute | argument list (Variant dicts) |
| `feeAsString` | string | no | default `"0"` |
| `UserData` | string | no | default `""` |

**Output (sample):**
```json
{
  "success": true,
  "dataResponse": {
    "transactionPackagedStr": "ScPack58...",
    "transactionInnerId": 7,
    "deployedAddress": "FwdrHR...",
    "recommendedFee": 0.1
  },
  "message": null
}
```

**When to use:** Build the canonical signing payload for a smart-contract
Deploy or Execute. Always capture `transactionInnerId` and pass it back to
the corresponding `*_deploy/_execute`.

---

### `smartcontract_deploy`
**Endpoint:** `POST /api/SmartContract/Deploy`  **Annotations:** destructive

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | same as Pack |
| `sourceCode` | string | yes | same as Pack |
| `byteCodeObjects` | list[{name,byteCode}] | yes | same as Pack |
| `TransactionSignature` | string (base58) | yes | ed25519 over decoded Pack bytes |
| `transactionInnerId` | int (≥1) | yes | MUST equal Pack's `transactionInnerId` |
| `feeAsString` | string | no | default `"0"` |
| `UserData` | string | no | default `""` |

**Output (sample):**
```json
{
  "success": true,
  "transactionId": "174580000.1",
  "deployedAddress": "FwdrHR...",
  "actualFee": "0.1",
  "message": null
}
```

**When to use:** Submit a signed Java contract to the network. Fee ~0.1 CS.

---

### `smartcontract_execute`
**Endpoint:** `POST /api/SmartContract/Execute`  **Annotations:** destructive

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | caller |
| `ReceiverPublicKey` | string (base58) | yes | contract address |
| `method` | string | yes | method name |
| `params` | list[Variant] | no | default `[]` |
| `TransactionSignature` | string (base58) | yes | ed25519 over decoded Pack bytes |
| `transactionInnerId` | int (≥1) | yes | MUST equal Pack's `transactionInnerId` |
| `feeAsString` | string | no | default `"0"` |
| `UserData` | string | no | default `""` |

**Output (sample):**
```json
{
  "success": true,
  "transactionId": "174580010.1",
  "actualFee": "0.05",
  "smartContractResult": null,
  "message": null
}
```

**When to use:** Call a method on a deployed Credits smart contract.

---

### `smartcontract_get`
**Endpoint:** `POST /api/SmartContract/Get`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `address` | string (base58) | yes | contract address |

**Output (sample):**
```json
{
  "address": "FwdrHR...",
  "deployer": "OwnerB58",
  "sourceCode": "public class C ...",
  "byteCodeObjects": [
    {"name": "C", "byteCode": "AAA="}
  ],
  "transactionsCount": 4,
  "success": true,
  "message": null
}
```

**When to use:** Read a deployed contract's full record (deployer, source,
bytecode, txCount).

---

### `smartcontract_methods`
**Endpoint:** `POST /api/SmartContract/Methods`  **Annotations:** read-only

**Input:** exactly one of:
| field | type | required | notes |
|---|---|---|---|
| `address` | string (base58) | one-of | inspect a deployed contract |
| `byteCodeObjects` | list[{name,byteCode}] | one-of | inspect pre-deploy |

**Output (sample):**
```json
{
  "methods": [
    {"name": "getCounter", "args": [], "returnType": "long"}
  ],
  "success": true,
  "message": null
}
```

**When to use:** Discover the public methods of a contract before calling
`smartcontract_pack(operation="execute")`.

---

### `smartcontract_state`
**Endpoint:** `POST /api/SmartContract/State`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `address` | string (base58) | yes | contract address |

**Output (sample):**
```json
{
  "fields": [
    {"name": "counter", "type": "long", "value": 4}
  ],
  "success": true,
  "message": null
}
```

**When to use:** Read the current public state (instance fields) of a
deployed contract — useful for dashboards and result inspection.

---

### `smartcontract_list_by_wallet`
**Endpoint:** `POST /api/SmartContract/ListByWallet`  **Annotations:** read-only

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `deployer` | string (base58) | yes | wallet that deployed the contracts |
| `offset` | int (≥0) | no | default 0 |
| `limit` | int (1..500) | no | default 10 |

**Output (sample):**
```json
{
  "contracts": [],
  "success": true,
  "message": null
}
```

**When to use:** Enumerate all smart contracts deployed by a given wallet.

---

## diag_*

Read-only network diagnostics. None of these take any input.

### `diag_get_active_nodes`
**Endpoint:** `POST /api/Diag/GetActiveNodes`  **Annotations:** read-only

**Input:** none.

**Output (sample):**
```json
{
  "nodes": [
    {"publicKey": "NodeB58", "version": "5.x"}
  ],
  "success": true,
  "message": null
}
```

**When to use:** List trusted/active nodes seen by the local Credits node.

---

### `diag_get_active_transactions_count`
**Endpoint:** `POST /api/Diag/GetActiveTransactionsCount`  **Annotations:** read-only

**Input:** none.

**Output (sample):**
```json
{
  "count": 17,
  "success": true,
  "message": null
}
```

**When to use:** Count of unconfirmed transactions currently in the mempool.

---

### `diag_get_node_info`
**Endpoint:** `POST /api/Diag/GetNodeInfo`  **Annotations:** read-only

**Input:** none.

**Output (sample):**
```json
{
  "nodeVersion": "5.x",
  "uptimeMs": 12345678,
  "blockchainTopHash": "Hash58...",
  "success": true,
  "message": null
}
```

**When to use:** Sanity check on the local node — version, uptime, top block
hash.

---

### `diag_get_supply`
**Endpoint:** `POST /api/Diag/GetSupply`  **Annotations:** read-only

**Input:** none.

**Output (sample):**
```json
{
  "initial": "250000000.0",
  "mined": "1234567.0",
  "currentSupply": "251234567.0",
  "success": true,
  "message": null
}
```

**When to use:** Network economics overview (initial + mined + currentSupply).
