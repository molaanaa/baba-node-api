import asyncio, httpx
from baba_mcp.client import GatewayClient
from baba_mcp.tools.userfields import UserFieldsEncodeInput, _encode_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=2000, max_retries=1)

def test_userfields_encode():
    def handler(req):
        return httpx.Response(200, json={
            "success": True, "userData": "uF58...", "message": None,
        })
    c = make_client(handler)
    inp = UserFieldsEncodeInput(
        contentHashAlgo="sha-256",
        contentHash="0011223344556677889900112233445566778899001122334455667788990011",
        contentCid="bafybeigdyrabc",
        mime="image/png",
        sizeBytes=1234567,
    )
    out = asyncio.run(_encode_impl(c, inp))
    assert out["userData"].startswith("uF58")
