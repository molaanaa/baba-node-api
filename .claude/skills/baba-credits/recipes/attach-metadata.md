# Recipe: attach userFields v1 metadata to a transaction (ArtVerse)

## When to use
The user wants to anchor an off-chain asset (image, video, document) to a
Credits transaction with verifiable metadata: SHA-256 hash, IPFS CID, MIME
type, size. Typical use case: ArtVerse minting — a transfer that doubles as
a "proof of authorship" record.

## Prerequisites
- The asset itself, hashed with SHA-256 (32 bytes, hex-encoded).
- An IPFS CID for the asset (the user pins it themselves; out of scope of
  this recipe).
- The MIME type and the size in bytes.
- `BABA_PRIVATE_KEY` available (or a wallet keystore that signs for A).

## Pipeline

### Step 1 — Compute SHA-256 of the asset
Off-chain, on the client:
```python
import hashlib
content_hash = hashlib.sha256(open(path, "rb").read()).hexdigest()
# e.g. "0011223344556677889900112233445566778899001122334455667788990011"
```

### Step 2 — Pin to IPFS
Out of scope of this recipe. The user (or the wallet app) pins the asset and
returns the CID, e.g. `bafybeigdyrabc`.

### Step 3 — Encode userFields v1 blob
```
userfields_encode({
    "contentHashAlgo": "sha-256",
    "contentHash": "0011223344556677889900112233445566778899001122334455667788990011",
    "contentCid": "bafybeigdyrabc",
    "mime": "image/png",
    "sizeBytes": 1234567
})
→ {
    "success": true,
    "userData": "uF58..."
  }
```
*Capture `userData` — it's a base58 blob ready to be embedded in a tx.*

### Step 4 — Pack the transaction with `UserData`
```
transaction_pack({
    "PublicKey": A,
    "ReceiverPublicKey": B,
    "amountAsString": "0.001",
    "feeAsString": "0",
    "UserData": "uF58..."
})
→ { "dataResponse": { "transactionPackagedStr": "<base58>",
                       "recommendedFee": 0.00874 },
    "success": true }
```

### Step 5 — Sign and submit
Continue with the standard `recipes/transfer-cs.md` pipeline starting at
Step 4 (sign client-side, then `transaction_execute` with the **same**
`UserData` value — drift here also breaks the signature).

```
sig_b58 = sign_packaged(packaged_str_b58, private_key_b58)
transaction_execute({
    "PublicKey": A,
    "ReceiverPublicKey": B,
    "amountAsString": "0.001",
    "feeAsString": "0",
    "UserData": "uF58...",
    "TransactionSignature": sig_b58
})
→ { "success": true, "transactionId": "174575023.1" }
```

### Step 6 — Verify (optional)
After the transaction seals, you can decode the on-chain `userData` back into
its structured form:
```
transaction_get_info({"transactionId": "174575023.1"})
→ { ..., "userData": "uF58...", ... }

userfields_decode({"userData": "uF58..."})
→ {
    "fields": {
      "contentHashAlgo": "sha-256",
      "contentHash": "0011...",
      "contentCid": "bafybeigdyrabc",
      "mime": "image/png",
      "sizeBytes": 1234567
    },
    "success": true
  }
```

## Common errors
- `"Transaction has wrong signature."` → `UserData` differs between Pack and
  Execute. The `UserData` blob is part of the packaged signing payload, so any
  drift breaks the signature. Always pass the **exact same** `userData` string.
- `userfields_encode` rejects `contentHash` of unexpected length → make sure
  `contentHashAlgo` matches the digest length (sha-256 → 64 hex chars).
- `node_unavailable` (503) → retry the transfer pipeline with backoff
  1s/2s/4s. Re-encoding is idempotent so steps 1-3 don't need re-running.

## On-chain confirmation
The metadata is anchored as soon as the transaction status is `"Success"` (a
single pool seal, ~3s). After that, anyone can:
1. Pull the `userData` from `transaction_get_info`.
2. Decode it with `userfields_decode`.
3. Fetch the asset from IPFS via the `contentCid`.
4. Recompute SHA-256 locally and compare against `contentHash` to verify the
   asset has not been tampered with.
