# Sign a packaged transaction with TypeScript (tweetnacl)

For wallet apps (mobile/web) embedded with an AI agent.

## Install
```bash
npm install tweetnacl bs58
```

## Code
```typescript
import nacl from "tweetnacl";
import bs58 from "bs58";

export function signPackaged(
  transactionPackagedStrB58: string,
  privateKeyB58: string,
): string {
  const raw = bs58.decode(transactionPackagedStrB58);
  const sk  = bs58.decode(privateKeyB58);   // 64 bytes (seed||pub)
  const sig = nacl.sign.detached(raw, sk);  // 64 bytes
  return bs58.encode(sig);
}
```

## Notes
- `nacl.sign.detached` expects the full 64-byte private key (seed||pub),
  unlike PyNaCl which wants the 32-byte seed only.
- For wallets with hardware-backed keystores (iOS Secure Enclave, Android
  StrongBox), replace `nacl.sign.detached` with the platform's `sign(bytes)`
  primitive — same input/output contract.
