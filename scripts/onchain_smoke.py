"""On-chain smoke for the BABA gateway extensions.

Reads sender key from .env (gitignored). Each step prints a clear header,
asks no input, and aborts the cascade on the first failure so we never
chain a broken assumption into the next step.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import base58
import requests
from dotenv import load_dotenv
from nacl.signing import SigningKey

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:5000")
SENDER_PRIV_B58 = os.environ["SENDER_PRIVATE_KEY"]
SENDER_PUB_B58 = os.environ["SENDER_PUBLIC_KEY"]
DEST_PUB_B58 = os.environ["DEST_PUBLIC_KEY"]


def section(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n{title}\n{bar}")


def post(path: str, body: dict, *, timeout: float = 30.0) -> dict:
    url = f"{GATEWAY}{path}"
    print(f"  POST {url}")
    print(f"   body: {json.dumps(body)[:200]}")
    r = requests.post(url, json=body, timeout=timeout)
    print(f"   HTTP {r.status_code}")
    try:
        out = r.json()
    except Exception:
        out = {"_raw": r.text}
    print(f"   resp: {json.dumps(out)[:600]}")
    return out


def signing_key() -> SigningKey:
    raw = base58.b58decode(SENDER_PRIV_B58)
    if len(raw) == 64:
        return SigningKey(raw[:32])
    if len(raw) == 32:
        return SigningKey(raw)
    raise SystemExit(f"private key must be 32 or 64 bytes, got {len(raw)}")


def sign_b58(payload: bytes) -> str:
    sk = signing_key()
    sig = sk.sign(payload).signature  # 64 bytes
    return base58.b58encode(sig).decode("ascii")


# ============================================================================
# D1 — simple transfer using existing /Transaction/Pack + /Transaction/Execute
# ============================================================================

def d1_transfer(amount: str = "0.001") -> dict:
    section("D1 — Transfer 0.001 CS (Pack → sign → Execute)")
    pack = post("/api/Transaction/Pack", {
        "publicKey": SENDER_PUB_B58,
        "receiverPublicKey": DEST_PUB_B58,
        "amountAsString": amount,
        "feeAsString": "0",
    })
    if not pack.get("success"):
        raise SystemExit(f"D1 abort: Pack failed: {pack}")

    packed_b58 = pack["dataResponse"]["transactionPackagedStr"]
    packed = base58.b58decode(packed_b58)
    print(f"   packed bytes ({len(packed)}B): {packed.hex()}")
    sig_b58 = sign_b58(packed)
    print(f"   signature (b58): {sig_b58}")

    exec_resp = post("/api/Transaction/Execute", {
        "publicKey": SENDER_PUB_B58,
        "receiverPublicKey": DEST_PUB_B58,
        "amountAsString": amount,
        "feeAsString": "0",
        "signature": sig_b58,
    })
    return exec_resp


# ============================================================================
# D2 — compile a minimal Java BasicCounter via /api/SmartContract/Compile
# ============================================================================

BASIC_COUNTER_SRC = """\
import com.credits.scapi.v0.SmartContract;

public class BasicCounter extends SmartContract {
    private int counter;

    public BasicCounter() {
        super();
        counter = 0;
    }

    public void increment() {
        counter += 1;
    }

    public void setCounter(int value) {
        counter = value;
    }

    public int getCounter() {
        return counter;
    }
}
"""

def d2_compile() -> dict:
    section("D2 — SmartContract/Compile (BasicCounter, read-only)")
    resp = post("/api/SmartContract/Compile", {"sourceCode": BASIC_COUNTER_SRC})
    if not resp.get("success"):
        raise SystemExit(f"D2 abort: Compile failed: {resp}")
    bcos = resp.get("byteCodeObjects") or []
    print(f"   compiled {len(bcos)} bytecode object(s)")
    for b in bcos:
        bc_len = len(b.get("byteCode", "") or "")
        print(f"     - {b.get('name')}: byteCode b64 length={bc_len}")
    return resp


# ============================================================================
# D3 — Deploy via /api/SmartContract/Deploy
# Note: the new endpoint expects the signature to cover the canonical Credits
# Transaction including the SmartContractInvocation; if the canonical scheme
# diverges from a transfer-only sign, the node rejects TransactionFlow before
# any fee is consumed (TransactionFlow validates signature first).
# ============================================================================

def _serialize_transfer_part(inner_id: int, source: bytes, target: bytes,
                             amount_int: int, amount_frac: int,
                             fee_bits: int, sf_bytes: bytes = b"\x00") -> bytes:
    import struct
    data = struct.pack("<Q", inner_id)[:6] + source + target
    data += struct.pack("<i", amount_int) + struct.pack("<q", amount_frac)
    data += struct.pack("<H", fee_bits) + struct.pack("B", 1)  # currency=1
    data += sf_bytes
    return data


def d3_deploy(compile_resp: dict) -> dict:
    section("D3 — SmartContract/Deploy (BasicCounter)")
    bcos = compile_resp.get("byteCodeObjects") or []
    if not bcos:
        raise SystemExit("D3 abort: no byteCodeObjects from Compile")

    # Resolve the next inner_id from the node
    info = post("/api/Monitor/GetWalletInfo", {"publicKey": SENDER_PUB_B58})
    if not info.get("success"):
        raise SystemExit(f"D3 abort: GetWalletInfo failed: {info}")
    inner_id = (info.get("lastTransaction") or 0) + 1
    print(f"   next inner_id: {inner_id}")

    sender = base58.b58decode(SENDER_PUB_B58)
    # Sign the transfer-part of the canonical Transaction. The node-counted
    # fee for a Deploy is well above the simple-transfer baseline, so we
    # encode a generous max fee (0.5 CS).
    fee_cs = 0.5
    # Mirror gateway.fee_to_bits() exactly so the signed payload matches.
    import math
    def _fee_to_bits(f: float) -> int:
        try:
            val = float(f); commission = 0
            if val < 0.0:
                commission += 32768
            else:
                val = math.fabs(val)
                expf = 0.0 if val == 0.0 else math.log10(val)
                expi = int(expf + 0.5 if expf >= 0.0 else expf - 0.5)
                if val > 0: val /= math.pow(10, expi)
                if val >= 1.0:
                    val *= 0.1; expi += 1
                commission += int(1024 * (expi + 18))
                commission += int(val * 1024)
            return commission
        except (ValueError, TypeError):
            return 0
    fee_bits = _fee_to_bits(fee_cs)
    payload = _serialize_transfer_part(inner_id, sender, b"", 0, 0, fee_bits)
    sig_b58 = sign_b58(payload)

    resp = post("/api/SmartContract/Deploy", {
        "publicKey": SENDER_PUB_B58,
        "signature": sig_b58,
        "sourceCode": BASIC_COUNTER_SRC,
        "byteCodeObjects": bcos,
        "feeAsString": str(fee_cs),
    })
    return resp


# ============================================================================
# D4 — Execute getCounter() via /api/SmartContract/Execute
# ============================================================================

def d4_execute(contract_address_b58: str) -> dict:
    section(f"D4 — SmartContract/Execute (getCounter on {contract_address_b58[:12]}...)")
    info = post("/api/Monitor/GetWalletInfo", {"publicKey": SENDER_PUB_B58})
    inner_id = (info.get("lastTransaction") or 0) + 1
    sender = base58.b58decode(SENDER_PUB_B58)
    target = base58.b58decode(contract_address_b58)
    fee_cs = 0.1
    import math
    def _fee_to_bits(f: float) -> int:
        try:
            val = float(f); commission = 0
            if val < 0.0:
                commission += 32768
            else:
                val = math.fabs(val)
                expf = 0.0 if val == 0.0 else math.log10(val)
                expi = int(expf + 0.5 if expf >= 0.0 else expf - 0.5)
                if val > 0: val /= math.pow(10, expi)
                if val >= 1.0:
                    val *= 0.1; expi += 1
                commission += int(1024 * (expi + 18))
                commission += int(val * 1024)
            return commission
        except (ValueError, TypeError):
            return 0
    fee_bits = _fee_to_bits(fee_cs)
    payload = _serialize_transfer_part(inner_id, sender, target, 0, 0, fee_bits)
    sig_b58 = sign_b58(payload)

    resp = post("/api/SmartContract/Execute", {
        "publicKey": SENDER_PUB_B58,
        "signature": sig_b58,
        "target": contract_address_b58,
        "method": "getCounter",
        "params": [],
        "feeAsString": str(fee_cs),
    })
    return resp


# ============================================================================
def main() -> None:
    print(f"Sender: {SENDER_PUB_B58}")
    print(f"Dest:   {DEST_PUB_B58}")
    print(f"Gateway: {GATEWAY}")

    d1 = d1_transfer()
    if not d1.get("success"):
        print("\n[D1 NOT successful — stopping cascade so we don't chain a broken sign]")
        sys.exit(1)
    print("\n[D1 OK — sign+broadcast pipeline is functional]")

    d2 = d2_compile()
    print("\n[D2 OK — Compile path on the new branch works]")

    d3 = d3_deploy(d2)
    if not d3.get("success"):
        print("\n[D3 failed — most likely canonical sign mismatch for SmartDeploy. No fee consumed.]")
        sys.exit(2)

    # The Deploy response carries the new contract's address either via
    # the messageError-free path or a dedicated field; fall back to deriving
    # it via /SmartContract/ListByWallet of the deployer.
    contract = (d3.get("dataResponse") or {}).get("smartContractResult") or d3.get("contractAddress")
    if not contract:
        time.sleep(3)
        listed = post("/api/SmartContract/ListByWallet",
                      {"publicKey": SENDER_PUB_B58, "offset": 0, "limit": 5})
        if listed.get("success") and listed.get("contracts"):
            contract = listed["contracts"][0].get("address")
    print(f"\n[D3 OK — contract addr: {contract}]")
    if not contract:
        print("D4 cannot run without a contract address; stopping.")
        sys.exit(3)

    time.sleep(2)
    d4 = d4_execute(contract)
    if not d4.get("success"):
        print("\n[D4 failed]")
        sys.exit(4)
    print("\n[ALL D-STEPS COMPLETED]")


if __name__ == "__main__":
    main()
