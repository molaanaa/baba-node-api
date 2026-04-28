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
# D3 — Deploy via /api/SmartContract/Pack -> sign -> /api/SmartContract/Deploy
# ============================================================================

def d3_deploy(compile_resp: dict) -> dict:
    section("D3 — SmartContract/Pack -> sign -> /SmartContract/Deploy (BasicCounter)")
    bcos = compile_resp.get("byteCodeObjects") or []
    if not bcos:
        raise SystemExit("D3 abort: no byteCodeObjects from Compile")

    # Bound the max fee we authorise (signed into the payload).
    fee_cs = 0.5

    pack = post("/api/SmartContract/Pack", {
        "publicKey": SENDER_PUB_B58,
        "sourceCode": BASIC_COUNTER_SRC,
        "byteCodeObjects": bcos,
        "feeAsString": str(fee_cs),
    })
    if not pack.get("success"):
        raise SystemExit(f"D3 abort: Pack failed: {pack}")

    packed_b58 = pack["dataResponse"]["transactionPackagedStr"]
    contract_addr = pack["dataResponse"].get("contractAddress") or pack.get("contractAddress")
    inner_id = pack.get("transactionInnerId")
    print(f"   inner_id: {inner_id}, contract address: {contract_addr}")

    payload = base58.b58decode(packed_b58)
    print(f"   packed bytes ({len(payload)}B), first 96B: {payload[:96].hex()}")
    sig_b58 = sign_b58(payload)
    print(f"   signature (b58): {sig_b58}")

    resp = post("/api/SmartContract/Deploy", {
        "publicKey": SENDER_PUB_B58,
        "signature": sig_b58,
        "sourceCode": BASIC_COUNTER_SRC,
        "byteCodeObjects": bcos,
        "feeAsString": str(fee_cs),
        "transactionInnerId": inner_id,
    })
    if resp.get("success"):
        resp.setdefault("contractAddress", contract_addr)
    return resp


# ============================================================================
# D4 — Execute getCounter() via /api/SmartContract/Pack -> sign -> Execute
# ============================================================================

def d4_execute(contract_address_b58: str) -> dict:
    section(f"D4 — SmartContract/Pack -> sign -> /SmartContract/Execute "
            f"(getCounter on {contract_address_b58[:12]}...)")
    fee_cs = 0.1

    pack = post("/api/SmartContract/Pack", {
        "publicKey": SENDER_PUB_B58,
        "target": contract_address_b58,
        "method": "getCounter",
        "params": [],
        "feeAsString": str(fee_cs),
    })
    if not pack.get("success"):
        raise SystemExit(f"D4 abort: Pack failed: {pack}")

    packed_b58 = pack["dataResponse"]["transactionPackagedStr"]
    inner_id = pack.get("transactionInnerId")
    payload = base58.b58decode(packed_b58)
    print(f"   packed bytes ({len(payload)}B), first 96B: {payload[:96].hex()}")
    sig_b58 = sign_b58(payload)

    resp = post("/api/SmartContract/Execute", {
        "publicKey": SENDER_PUB_B58,
        "signature": sig_b58,
        "target": contract_address_b58,
        "method": "getCounter",
        "params": [],
        "feeAsString": str(fee_cs),
        "transactionInnerId": inner_id,
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
    contract = (
        d3.get("contractAddress")
        or (d3.get("dataResponse") or {}).get("contractAddress")
        or (d3.get("dataResponse") or {}).get("smartContractResult")
    )
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
