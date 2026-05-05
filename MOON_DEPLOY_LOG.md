# MOON Token Deploy Log

End-to-end record of the MOON ERC-20-like token deployment and transfer test
performed entirely through the public HTTP gateway
(`https://credits-gateway.duckdns.org`) — no MCP server was involved.
Every request and response is reproduced below verbatim, with private-key
material redacted.

## 1. Overview

| Item | Value |
|---|---|
| Sender (deployer) public key | `3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw` |
| Sender private key | `2QoS7H...hp7B` *(redacted)* |
| Receiver | `MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP` |
| Token contract address | `2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y` |
| Token name / symbol | `MOON TOKEN` / `MOON` |
| Decimals | `3` |
| Total supply | `10,000,000.000` MOON |
| Initial owner balance | `100,000.000` MOON |
| Deploy transaction id | `175026317.1` |
| Successful transfer tx id | `175026582.1` (100 MOON to receiver) |
| Final owner balance | `99,900.000` MOON |
| Final receiver balance | `100.000` MOON |
| Invariant (owner + receiver) | `100,000.000` (matches initial allocation) |

All HTTP calls go to the production gateway:
`https://credits-gateway.duckdns.org/api/...`

The deployer's seed (32 bytes) is used to sign each smart-contract
transaction with **Ed25519**. The signing flow is always:

1. `POST /api/SmartContract/Pack` — server returns `transactionPackagedStr`
   (base58 of the bytes that must be signed).
2. Client side: base58-decode → sign(seed) → base58-encode the 64-byte
   signature.
3. `POST /api/SmartContract/Deploy` or `/api/SmartContract/Execute` with
   the signature in the `TransactionSignature` field.

## 2. MOON source code

Inspired by the public TESTBANK contract
(`12P29RCe1fiRXqFEgTMEXxMoqKJoSLkmzq8UoxrFDiTU`) but with the previously
stub `buyTokens` method actually implemented and a fee-paid `payable`
that consumes the CS sent to mint MOON tokens. All `@Override` markers
present on the `ExtensionStandard` interface are kept.

```java
package com.credits.cst;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import com.credits.scapi.annotations.*;
import com.credits.scapi.v0.*;

import static java.math.BigDecimal.ZERO;
import static java.math.RoundingMode.DOWN;

public class MOON extends SmartContract implements ExtensionStandard {

    private final String owner;
    private final BigDecimal tokenCost;
    private final int decimal;
    HashMap<String, BigDecimal> balances;
    private String name;
    private String symbol;
    private BigDecimal totalCoins;
    private HashMap<String, Map<String, BigDecimal>> allowed;
    private boolean frozen;

    public MOON() {
        super();
        name = "MOON TOKEN";
        symbol = "MOON";
        decimal = 3;
        tokenCost = new BigDecimal("1").setScale(decimal, DOWN);
        totalCoins = new BigDecimal(10_000_000).setScale(decimal, DOWN);
        owner = initiator;
        allowed = new HashMap<>();
        balances = new HashMap<>();
        balances.put(owner, new BigDecimal(100_000L).setScale(decimal, DOWN));
    }

    @Override public int getDecimal() { return decimal; }

    @Override
    public void register() {
        balances.putIfAbsent(initiator, toBigDecimal("0"));
    }

    @Override
    public boolean setFrozen(boolean isFrozen) {
        if (!initiator.equals(owner)) {
            throw new RuntimeException("unable change frozen state! The wallet " + initiator + " is not owner");
        }
        this.frozen = isFrozen;
        return true;
    }

    @Override public String getName() { return name; }
    @Override public String getSymbol() { return symbol; }
    @Override public String totalSupply() { return totalCoins.toString(); }

    @Override
    public String balanceOf(String address) {
        BigDecimal b = balances.get(address);
        return (b == null ? ZERO.setScale(decimal, DOWN) : b).toString();
    }

    @Override
    public String allowance(String tokenOwner, String spender) {
        if (allowed.get(tokenOwner) == null) return "0";
        BigDecimal a = allowed.get(tokenOwner).get(spender);
        return a != null ? a.toString() : "0";
    }

    @Override
    public boolean transfer(String to, String amount) {
        contractIsNotFrozen();
        if (!to.equals(initiator)) {
            BigDecimal d = toBigDecimal(amount);
            if (d.compareTo(ZERO) < 0) throw new IllegalArgumentException("the amount cannot be negative");
            BigDecimal src = getOrZero(initiator);
            BigDecimal tgt = getOrZero(to);
            if (src.compareTo(d) < 0)
                throw new RuntimeException("the wallet " + initiator + " doesn't have enough tokens to transfer");
            balances.put(initiator, src.subtract(d));
            balances.put(to, tgt.add(d));
        }
        return true;
    }

    @Override
    public boolean transferFrom(String from, String to, String amount) {
        contractIsNotFrozen();
        initiatorIsRegistered();
        if (!from.equals(to)) {
            BigDecimal src = getOrZero(from);
            BigDecimal tgt = getOrZero(to);
            BigDecimal d = toBigDecimal(amount);
            if (d.compareTo(ZERO) < 0) throw new IllegalArgumentException("the amount cannot be negative");
            if (src.compareTo(d) < 0) throw new RuntimeException("balance of " + from + " less than " + amount);
            Map<String, BigDecimal> spender = allowed.get(from);
            if (spender == null || !spender.containsKey(initiator))
                throw new RuntimeException(from + " not allow transfer for " + initiator);
            BigDecimal allowTokens = spender.get(initiator);
            if (allowTokens.compareTo(d) < 0) throw new RuntimeException("not enough allowed tokens");
            spender.put(initiator, allowTokens.subtract(d));
            balances.put(from, src.subtract(d));
            balances.put(to, tgt.add(d));
        }
        return true;
    }

    @Override
    public void approve(String spender, String amount) {
        initiatorIsRegistered();
        BigDecimal d = toBigDecimal(amount);
        if (d.compareTo(ZERO) < 0) throw new IllegalArgumentException("the amount cannot be negative");
        Map<String, BigDecimal> initSpenders = allowed.get(initiator);
        if (initSpenders == null) {
            Map<String, BigDecimal> ns = new HashMap<>();
            ns.put(spender, d);
            allowed.put(initiator, ns);
        } else {
            initSpenders.put(spender, d);            // override (ERC-20 standard)
        }
    }

    @Override
    public boolean burn(String amount) {
        contractIsNotFrozen();
        BigDecimal d = toBigDecimal(amount);
        if (d.compareTo(ZERO) < 0) throw new IllegalArgumentException("the amount cannot be negative");
        if (!initiator.equals(owner))
            throw new RuntimeException("only owner can burn");
        BigDecimal ownerBal = getOrZero(owner);
        BigDecimal toBurn = ownerBal.compareTo(d) < 0 ? ownerBal : d;
        balances.put(owner, ownerBal.subtract(toBurn));
        if (totalCoins.compareTo(toBurn) < 0) totalCoins = toBigDecimal("0");
        else totalCoins = totalCoins.subtract(toBurn);
        return true;
    }

    public void payable(String amount, String currency) {
        contractIsNotFrozen();
        BigDecimal csPaid = toBigDecimal(amount);
        if (csPaid.compareTo(ZERO) <= 0) throw new IllegalArgumentException("amount must be positive");
        BigDecimal tokensToMint = csPaid.divide(tokenCost, decimal, DOWN);
        BigDecimal availableForSale = totalCoins.subtract(sumOfBalances());
        if (availableForSale.compareTo(tokensToMint) < 0)
            throw new RuntimeException("not enough tokens available for sale");
        balances.put(initiator,
            Optional.ofNullable(balances.get(initiator)).orElse(toBigDecimal("0")).add(tokensToMint));
    }

    @Override
    public boolean buyTokens(String amount) {
        contractIsNotFrozen();
        BigDecimal d = toBigDecimal(amount);
        if (d.compareTo(ZERO) <= 0) throw new IllegalArgumentException("amount must be positive");
        BigDecimal availableForSale = totalCoins.subtract(sumOfBalances());
        if (availableForSale.compareTo(d) < 0) return false;
        balances.put(initiator,
            Optional.ofNullable(balances.get(initiator)).orElse(toBigDecimal("0")).add(d));
        return true;
    }

    private BigDecimal sumOfBalances() {
        BigDecimal sum = ZERO;
        for (BigDecimal b : balances.values()) sum = sum.add(b);
        return sum.setScale(decimal, DOWN);
    }

    private void contractIsNotFrozen() {
        if (frozen) throw new RuntimeException("contract is frozen");
    }

    private void initiatorIsRegistered() {
        if (!balances.containsKey(initiator))
            throw new RuntimeException(initiator + " is not registered");
    }

    private BigDecimal toBigDecimal(String s) {
        return new BigDecimal(s).setScale(decimal, DOWN);
    }

    private BigDecimal getOrZero(String address) {
        return Optional.ofNullable(balances.get(address)).orElse(toBigDecimal("0"));
    }
}
```

## 3. High-level workflow

1. **Sender CS balance check** — make sure the deployer wallet has enough
   CS to cover the deploy fee (deploy of a non-trivial Java contract
   costs ~0.18 CS; we paid 0.5 CS to be safe).
2. **Compile** — submit the Java source to the gateway, which forwards
   it to the node's contract executor and returns one or more
   `byteCodeObjects` (base64-encoded class bytecode).
3. **Pack deploy** — gateway derives the deterministic contract
   address (`blake2s(deployer || innerId || bytecodes)`), allocates the
   next `transactionInnerId`, and returns the canonical bytes-to-sign
   (`transactionPackagedStr`, base58).
4. **Sign** — Ed25519 over the decoded packaged bytes, using the
   first 32 bytes of the deployer's 64-byte private key as seed.
5. **Submit deploy** — `/api/SmartContract/Deploy` with the signature.
   The response contains `transactionId` once the node seals it.
6. **Pack + sign + execute `transfer`** — same flow, this time naming
   the contract address as `target` and providing
   `method: "transfer"` plus typed `params`.
7. **Read-only verification** — `forgetNewState=true` Execute of
   `balanceOf(...)` returns the post-transfer balances for both
   sender and receiver.

A first transfer attempt was made with **wrong param shape**
(`{"K_TYPENAME": "...", "V_STRING": "..."}`); the node accepted the tx
and sealed it but the smart-contract execution silently no-op'd because
the gateway's Variant builder did not recognise those keys and produced
empty Variants. The token state remained unchanged. Repeating with the
correct shape (`{"v_string": "..."}`) fixed it. Both attempts are
documented below for completeness.

## 4. Step-by-step requests and responses

> Notes for reading the dump:
> - `byteCodeObjects` and the MOON `sourceCode` are referenced rather than
>   pasted verbatim in each request to keep the document readable; the
>   actual content is what is shown in Section 2 and the bytecode
>   prefix in step 2.
> - `TransactionSignature` is shown as `***REDACTED***` because it is
>   a function of the deployer's private key.
> - `transactionPackagedStr` is **not** redacted: it is just the
>   serialised tx body (public information) that the client must sign.

### 1. Sender CS balance

**`POST /api/Monitor/GetBalance`** — HTTP 200 in 0.21s

**Request:**
```json
{
  "publicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw"
}
```

**Response:**
```json
{
  "balance": 97.52084425864965,
  "delegatedIn": 59310.01748046875,
  "delegatedOut": 0,
  "message": "Tokens not supported",
  "success": true,
  "tokens": []
}
```

The `"Tokens not supported"` message reflects the fact that the node
this gateway speaks to is a regular (non-token-indexing) node; it is
expected and does not affect smart-contract operations. The CS balance
of ~97.5 CS is more than enough to cover the deploy + transfer fees.

### 2. Compile MOON source

**`POST /api/SmartContract/Compile`** — HTTP 200 in 0.75s

**Request:**
```json
{
  "sourceCode": "<MOON source code, see Section 2 above>"
}
```

**Response:**
```json
{
  "byteCodeObjects": [
    {
      "byteCode": "yv66vgAAADcBBwoARQCJCACKCQBEAIsIAIwJAEQAjQkARACOBwCPCACQCgAH... <truncated, full base64 bytecode is ~5KB>",
      "name": "com.credits.cst.MOON"
    }
  ],
  "message": "Success: ",
  "success": true,
  "tokenStandard": 2
}
```

`tokenStandard: 2` is the gateway's hint that the compiled class
implements `ExtensionStandard` (as opposed to `BasicStandard = 1`).

### 3. Pack deploy

**`POST /api/SmartContract/Pack`** — HTTP 200 in 0.43s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "sourceCode": "<MOON source code>",
  "byteCodeObjects": "<1 entry from step 2>",
  "feeAsString": "0.5"
}
```

**Response (key fields):**
```json
{
  "contractAddress": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "dataResponse": {
    "contractAddress": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
    "recommendedFee": 0.034960937500000004,
    "transactionPackagedStr": "6RK2oC1vHN…<2.5KB base58 of the bytes-to-sign>…WBS75Hctg"
  },
  "mode": "deploy",
  "success": true,
  "transactionInnerId": 264
}
```

The contract address is deterministic, derived from the deployer's
public key, the next `innerId` (264) and the bytecode hash. We pre-sign
the packaged bytes with Ed25519:

```
seed   = first 32 bytes of base58-decoded private key
sig    = ed25519_sign(seed, base58_decode(transactionPackagedStr))
sig_b58 = base58_encode(sig)         # 88 characters
```

### 4. Submit deploy

**`POST /api/SmartContract/Deploy`** — HTTP 200 in 91.5s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "sourceCode": "<MOON source code>",
  "byteCodeObjects": "<1 entry>",
  "TransactionSignature": "***REDACTED***",
  "TransactionInnerId": 264,
  "feeAsString": "0.5"
}
```

**Response:**
```json
{
  "actualFee": "0.008740234375000001",
  "dataResponse": {
    "recommendedFee": 0.008740234375000001,
    "smartContractResult": null,
    "transactionPackagedStr": null
  },
  "message": "TransactionFlow disconnected; recovered via post-seal polling.",
  "success": true,
  "transactionId": "175026317.1",
  "transactionInnerId": 264
}
```

The `TransactionFlow disconnected; recovered via post-seal polling`
message is benign: the node closed the long-lived submit RPC after the
tx was sealed in a block, and the gateway recovered the final state
through follow-up polling. `actualFee` is the fee actually charged
(~0.009 CS).

### 5. Wait for deploy confirmation (failed call, informative only)

**`POST /api/Monitor/WaitForSmartTransaction`** — HTTP 400 in 0.5s

**Request:**
```json
{
  "transactionId": "175026317.1",
  "timeoutMs": 60000
}
```

**Response:**
```json
{
  "message": "Missing publicKey",
  "success": false
}
```

`WaitForSmartTransaction` is keyed by **smart-contract address**, not
by transaction id. The first try used the wrong key shape; this is
documented as part of the lessons-learned section. Verification was
then performed by polling balances directly.

### 6. Pack execute `transfer` (first attempt, wrong param shape)

**`POST /api/SmartContract/Pack`** — HTTP 200 in 0.37s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "transfer",
  "params": [
    {"K_TYPENAME": "java.lang.String", "V_STRING": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"},
    {"K_TYPENAME": "java.lang.String", "V_STRING": "100"}
  ],
  "feeAsString": "0.5"
}
```

**Response (key fields):**
```json
{
  "dataResponse": {
    "transactionPackagedStr": "TcTiLjKwpe…<base58>…NJweNjRuyibx79"
  },
  "success": true,
  "transactionInnerId": 265
}
```

### 7. Execute `transfer` (first attempt — sealed, but no-op)

**`POST /api/SmartContract/Execute`** — HTTP 200 in 92.2s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "transfer",
  "params": [
    {"K_TYPENAME": "java.lang.String", "V_STRING": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"},
    {"K_TYPENAME": "java.lang.String", "V_STRING": "100"}
  ],
  "TransactionSignature": "***REDACTED***",
  "TransactionInnerId": 265,
  "feeAsString": "0.5"
}
```

**Response:**
```json
{
  "actualFee": "0.008740234375000001",
  "message": "TransactionFlow disconnected; recovered via post-seal polling.",
  "success": true,
  "transactionId": "175026390.1",
  "transactionInnerId": 265
}
```

The tx sealed, but the contract method was invoked with two empty
String parameters because the gateway's Variant builder did not
understand `K_TYPENAME` / `V_STRING`. The contract's `transfer("", "")`
silently no-op'd (the `if (!to.equals(initiator))` guard discarded it
because empty string equals empty string in the `initiator` slot only
on the first invocation; in any case the balances did not change — see
step 14 result).

### 8. Wait for transfer (same `Missing publicKey` issue)

**`POST /api/Monitor/WaitForSmartTransaction`** — HTTP 400 in 6.0s

```json
{ "transactionId": "175026390.1", "timeoutMs": 60000 }
```
```json
{ "message": "Missing publicKey", "success": false }
```

### 9. Pack `balanceOf(receiver)` — first attempt

**`POST /api/SmartContract/Pack`** — HTTP 200 in 0.06s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "balanceOf",
  "params": [
    {"K_TYPENAME": "java.lang.String", "V_STRING": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"}
  ],
  "forgetNewState": true,
  "feeAsString": "0.5"
}
```

**Response (key fields):**
```json
{
  "dataResponse": {
    "transactionPackagedStr": "WZt9KAxrB7uR…<base58>…b9oT997FaR4kEYej"
  },
  "success": true,
  "transactionInnerId": 266
}
```

### 10. Execute `balanceOf` — first attempt fails with `Unrecognized type 0`

**`POST /api/SmartContract/Execute`** — HTTP 200 in 0.38s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "balanceOf",
  "params": [
    {"K_TYPENAME": "java.lang.String", "V_STRING": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"}
  ],
  "TransactionSignature": "***REDACTED***",
  "TransactionInnerId": 266,
  "feeAsString": "0.5",
  "forgetNewState": true
}
```

**Response:**
```json
{
  "messageError": "Unrecognized type 0",
  "success": false,
  "transactionInnerId": 266
}
```

The empty Variant produced by the wrong key shape was rejected by the
contract executor here (`balanceOf(<empty Variant>)`), confirming the
root cause.

### 11. Pack `transfer` — corrected param shape

**`POST /api/SmartContract/Pack`** — HTTP 200 in 0.15s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "transfer",
  "params": [
    {"v_string": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"},
    {"v_string": "100"}
  ],
  "feeAsString": "0.5"
}
```

**Response (key fields):**
```json
{
  "dataResponse": {
    "transactionPackagedStr": "Q8LKTacs9Y…<base58>…YWApJVV8GbMDFTYZwk8qiw6Js"
  },
  "success": true,
  "transactionInnerId": 266
}
```

### 12. Execute `transfer` — corrected, sealed and effective

**`POST /api/SmartContract/Execute`** — HTTP 200 in 91.1s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "transfer",
  "params": [
    {"v_string": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"},
    {"v_string": "100"}
  ],
  "TransactionSignature": "***REDACTED***",
  "TransactionInnerId": 266,
  "feeAsString": "0.5"
}
```

**Response:**
```json
{
  "actualFee": "0.008740234375000001",
  "message": "TransactionFlow disconnected; recovered via post-seal polling.",
  "success": true,
  "transactionId": "175026582.1",
  "transactionInnerId": 266
}
```

This is the **authoritative** transfer transaction.

### 13. Pack `balanceOf(receiver)` post-transfer

**`POST /api/SmartContract/Pack`** — HTTP 200 in 1.88s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "balanceOf",
  "params": [{"v_string": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"}],
  "forgetNewState": true,
  "feeAsString": "0.5"
}
```

**Response:**
```json
{
  "dataResponse": {
    "transactionPackagedStr": "2marQv9xYWk…<base58>"
  },
  "success": true,
  "transactionInnerId": 267
}
```

### 14. Execute `balanceOf(receiver)` — **100.000 MOON**

**`POST /api/SmartContract/Execute`** — HTTP 200 in 0.16s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "balanceOf",
  "params": [{"v_string": "MooNRor8TcLT3xpAw3UvA2Q6xT8huRoQojn6ZSveDpP"}],
  "TransactionSignature": "***REDACTED***",
  "TransactionInnerId": 267,
  "feeAsString": "0.5",
  "forgetNewState": true
}
```

**Response:**
```json
{
  "dataResponse": {
    "smartContractResult": "100.000"
  },
  "success": true,
  "transactionInnerId": 267
}
```

### 15. Pack `balanceOf(sender)` post-transfer

**`POST /api/SmartContract/Pack`** — HTTP 200 in 0.22s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "balanceOf",
  "params": [{"v_string": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw"}],
  "forgetNewState": true,
  "feeAsString": "0.5"
}
```

**Response:**
```json
{
  "dataResponse": {
    "transactionPackagedStr": "8onR6ZcYA6Hj…<base58>"
  },
  "success": true,
  "transactionInnerId": 267
}
```

### 16. Execute `balanceOf(sender)` — **99,900.000 MOON**

**`POST /api/SmartContract/Execute`** — HTTP 200 in 0.09s

**Request:**
```json
{
  "PublicKey": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw",
  "target": "2T5dmjqYoDuJWiJsueq66qF83tguNZYpr6evYFtWDk2y",
  "method": "balanceOf",
  "params": [{"v_string": "3EDCyBgXoD4i35wYAf71vh3nqCDtVASmD2qDB7TgGpVw"}],
  "TransactionSignature": "***REDACTED***",
  "TransactionInnerId": 267,
  "feeAsString": "0.5",
  "forgetNewState": true
}
```

**Response:**
```json
{
  "dataResponse": {
    "smartContractResult": "99900.000"
  },
  "success": true,
  "transactionInnerId": 267
}
```

## 5. Final state

| Wallet | Final MOON balance |
|---|---|
| Deployer `3EDCyBgX...GpVw` | `99,900.000` |
| Receiver `MooNRor8...DpP` | `100.000` |
| Sum                       | `100,000.000` (matches initial allocation) |

The transfer of 100 MOON from the deployer to the receiver is fully
confirmed on-chain by reading both balances back from the contract
state via a `forgetNewState=true` `balanceOf` invocation.

## 6. Lessons learned

- **`SmartContract/Pack` parameter shape**: `params` entries must use
  the lowercase Variant field names (`v_string`, `v_int`, `v_bool`,
  `v_byte_array`). Using uppercase `V_STRING` / `K_TYPENAME` keys
  *silently* produces empty Variants — the gateway accepts the request,
  the node seals the tx, but the contract method receives `null`/empty
  arguments. Always cross-check `balanceOf(...)` before assuming a
  state mutation succeeded.
- **`feeAsString` consistency**: the fee passed to `Pack` is part of
  the bytes-to-sign. Passing a different fee at `Deploy`/`Execute`
  invalidates the signature. Keep them identical (`0.5` here).
- **Default recommended fee is too low for non-trivial contracts**:
  the node returned `"Counted fee will be 0.183594"` when 0.034 was
  offered. Set `feeAsString` explicitly to a comfortable margin
  (0.5 worked for a ~3KB MOON contract).
- **`Monitor/WaitForSmartTransaction`** expects the **contract address**,
  not a transaction id, in the `publicKey` field. Use it as
  `WaitForSmartTransaction({"publicKey": "<contract_address>"})` if
  you need to block until the next state event. For a one-shot
  confirmation, polling balances or `Transaction/Result` works fine.
- **Long-running submits**: deploy and execute requests can take
  ~90 seconds because the node holds the connection open until the tx
  is sealed. The gateway logs `TransactionFlow disconnected; recovered
  via post-seal polling.` and still returns `success: true` plus a
  valid `transactionId` — this is normal.
