import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.tools.tokens import TokensInfoInput, _info_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=2000, max_retries=1)

def test_tokens_info():
    def handler(req):
        return httpx.Response(200, json={
            "name": "TestTok", "code": "TST", "decimals": 18,
            "totalSupply": "1000000", "owner": "OwnerB58",
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_info_impl(c, TokensInfoInput(token="TokB58")))
    assert out["code"] == "TST"
