# Sign a packaged transaction with Python (PyNaCl)

Validated on-chain 2026-04-27 with 3 mainnet transfers (e.g. tx 174575023.1).

## Install
```bash
pip install pynacl base58
```

## Code (5 lines)
```python
import base58, nacl.signing

def sign_packaged(transaction_packaged_str_b58: str, private_key_b58: str) -> str:
    raw = base58.b58decode(transaction_packaged_str_b58)
    sk  = nacl.signing.SigningKey(base58.b58decode(private_key_b58)[:32])
    sig = sk.sign(raw).signature           # 64 bytes
    return base58.b58encode(sig).decode()
```

## Notes
- The Credits private key is 64 bytes base58: first 32 = seed (used by ed25519),
  last 32 = derived public key. PyNaCl's `SigningKey` expects only the seed.
- The signature is over the **raw bytes** of the packaged blob, NOT over the
  base58 string. Decode first, then sign.
- Output is a 64-byte signature, base58-encoded — ready for `TransactionSignature`.

## Where to keep the private key
- An "agent with a key" reads it from `BABA_PRIVATE_KEY` env var.
- A wallet with embedded AI uses its own keystore (Keychain, Android Keystore,
  hardware wallet). The keystore exposes a `sign(bytes) -> bytes` API; use that
  in place of `nacl.signing.SigningKey`.
- NEVER pass the private key to any MCP tool or to the gateway.
