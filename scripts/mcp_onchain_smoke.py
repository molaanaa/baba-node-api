"""Manual end-to-end smoke test of the baba-credits MCP server against a real
Credits node. Not run in CI. Requires:

  - the node reachable via the gateway (default http://127.0.0.1:5000)
  - an env var BABA_PRIVATE_KEY (base58, 64 bytes) of a funded wallet
  - the corresponding env var BABA_PUBLIC_KEY (base58)
  - BABA_RECEIVER (base58) for the destination wallet

Usage:
    BABA_PRIVATE_KEY=... BABA_PUBLIC_KEY=... \\
    BABA_RECEIVER=...                          \\
    python3 scripts/mcp_onchain_smoke.py
"""
from __future__ import annotations
import os, asyncio, json, base58
import nacl.signing
from mcp.types import CallToolRequest, CallToolRequestParams
from baba_mcp.server import load_config, build_server

PK   = os.environ["BABA_PUBLIC_KEY"]
SK   = os.environ["BABA_PRIVATE_KEY"]
RCV  = os.environ["BABA_RECEIVER"]


def sign_packaged(b58: str) -> str:
    raw = base58.b58decode(b58)
    sk  = nacl.signing.SigningKey(base58.b58decode(SK)[:32])
    return base58.b58encode(sk.sign(raw).signature).decode()


async def call(server, name: str, args: dict):
    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=args),
    )
    result = await handler(req)
    return json.loads(result.root.content[0].text)


async def main():
    cfg = load_config()
    server = build_server(cfg)

    # Read-only checks
    bal = await call(server, "monitor_get_balance", {"PublicKey": PK})
    print("balance:", bal["balance"])
    supply = await call(server, "diag_get_supply", {})
    print("supply:", supply)

    # Transfer 0.001 CS PK -> RCV
    pack = await call(server, "transaction_pack", {
        "PublicKey": PK, "ReceiverPublicKey": RCV,
        "amountAsString": "0.001", "feeAsString": "0", "UserData": "",
    })
    pkg = pack["dataResponse"]["transactionPackagedStr"]
    print("pack ok, recommendedFee:", pack["dataResponse"]["recommendedFee"])

    sig = sign_packaged(pkg)
    exe = await call(server, "transaction_execute", {
        "PublicKey": PK, "ReceiverPublicKey": RCV,
        "amountAsString": "0.001", "feeAsString": "0", "UserData": "",
        "TransactionSignature": sig,
    })
    print("execute:", exe.get("transactionId"), exe.get("success"))
    assert exe["success"], exe.get("messageError")

    # Confirmation
    info = await call(server, "transaction_get_info",
                      {"transactionId": exe["transactionId"]})
    print("status:", info.get("status"))


if __name__ == "__main__":
    asyncio.run(main())
